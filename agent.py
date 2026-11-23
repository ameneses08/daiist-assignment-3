"""
Assignment 3: the agent (`main.py ask "question"` runs `python agent.py "question"`).

LangChain `create_agent` on Gemini, with server.py's tools loaded over MCP (stdio, the same way
an editor starts it) and AGENTS.md as the system prompt. Guardrails:

1. Approval: add_document never runs without a human saying yes (HumanInTheLoopMiddleware).
   With no terminal to ask (evaluation, check.py) the call is rejected.
2. Call limits: at most MAX_SEARCHES tool calls and MAX_MODEL_CALLS model calls per question.
3. Citation check (my extra guardrail): every [source | location] in the answer must point to a
   passage that search actually returned, and a non-refusal must cite something. If not, the
   model gets one chance to fix it; if it still fails, the answer is withheld and replaced by
   the refusal sentence.

`Harness.ask()` returns the answer with its tool trace, tokens and time, for evaluate.py.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import rag
from api_key import load_api_key

ROOT = Path(__file__).resolve().parent
SYSTEM_PROMPT = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
MODEL = os.environ.get("AGENT_MODEL", "gemini-3.5-flash-lite")
MAX_SEARCHES = 4          # AGENTS.md asks for up to 3; one spare before the limit stops it
MAX_MODEL_CALLS = 8
REFUSAL = "I can't answer this from the documents I have."


def is_refusal(answer: str) -> bool:
    return REFUSAL.lower().rstrip(".") in answer.lower().replace("’", "'")


def text_of(message) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)


async def load_tools(session: ClientSession) -> list[StructuredTool]:
    """Wrap each MCP tool of server.py as a LangChain tool."""
    tools = []
    for tool in (await session.list_tools()).tools:
        async def call(_name: str = tool.name, **kwargs) -> str:
            result = await session.call_tool(_name, kwargs)
            return "\n".join(getattr(c, "text", "") for c in result.content)
        tools.append(StructuredTool.from_function(
            coroutine=call, name=tool.name, description=tool.description or "", args_schema=tool.input_schema))
    return tools


def ask_human(action: dict) -> bool:
    """Approval for add_document: ask on the terminal; with no terminal, refuse."""
    if not sys.stdin.isatty():
        print(f"[approval] {action['name']}({action['args']}) rejected: no one at the terminal to approve it.",
              file=sys.stderr)
        return False
    print(f"\nThe agent wants to run {action['name']} with {action['args']}.", file=sys.stderr)
    print("This adds the file to the index for every later question and spends embedding quota.", file=sys.stderr)
    print("Approve? [y/N] ", end="", file=sys.stderr, flush=True)   # stderr: visible even when stdout is piped
    return input().strip().lower() in ("y", "yes")


class Harness:
    """One MCP connection to server.py and one agent, reused across questions."""

    def __init__(self, approve: Callable[[dict], bool] = ask_human, model: str = MODEL):
        self.approve, self.model_name = approve, model

    async def __aenter__(self) -> "Harness":
        load_api_key()
        self._stack = AsyncExitStack()
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")], cwd=str(ROOT),
                                       env={**os.environ})
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        tools = await load_tools(self.session)
        # Gemini 3 models are meant to run at their default temperature (Google advises against lowering it).
        model = ChatGoogleGenerativeAI(model=self.model_name, max_retries=6)
        self.agent = create_agent(
            model, tools, system_prompt=SYSTEM_PROMPT, checkpointer=InMemorySaver(),
            middleware=[
                HumanInTheLoopMiddleware(interrupt_on={"add_document": True}),
                ToolCallLimitMiddleware(run_limit=MAX_SEARCHES),
                ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="end"),
            ],
        )
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    async def _run(self, message, config: dict, events: list) -> dict:
        state = await self.agent.ainvoke(message, config)
        while state.get("__interrupt__"):                      # approval before add_document
            decisions = []
            for interrupt in state["__interrupt__"]:
                for action in interrupt.value["action_requests"]:
                    ok = self.approve(action)
                    events.append({"guardrail": "approval", "tool": action["name"], "args": action["args"],
                                   "approved": ok})
                    decisions.append({"type": "approve"} if ok else
                                     {"type": "reject", "message": "The human did not approve adding this document."})
            state = await self.agent.ainvoke(Command(resume={"decisions": decisions}), config)
        return state

    async def ask(self, question: str) -> dict:
        started = time.time()
        config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 40}
        events: list[dict] = []
        state = await self._run({"messages": [HumanMessage(question)]}, config, events)
        answer, retrieved = self._answer(state), self._retrieved(state)

        # Guardrail: citations must match retrieved passages; one chance to fix, then withhold.
        # Not applied to a turn that was an add_document request: its reply reports an action, not facts.
        added = any(c["name"] == "add_document" for m in state["messages"] if isinstance(m, AIMessage)
                    for c in m.tool_calls)
        problem = None if added else self._citation_problem(answer, retrieved)
        if problem:
            events.append({"guardrail": "citations", "attempt": 1, "problem": problem, "draft": answer})
            fix = (f"Your answer was not accepted: {problem} Rewrite it using only the passages already "
                   f"retrieved, citing each claim with a label copied exactly from a search result, or reply "
                   f"with \"{REFUSAL}\" if they do not answer the question.")
            state = await self._run({"messages": [HumanMessage(fix)]}, config, events)
            answer, retrieved = self._answer(state), self._retrieved(state)
            problem = self._citation_problem(answer, retrieved)
            if problem:
                events.append({"guardrail": "citations", "attempt": 2, "problem": problem, "draft": answer})
                answer = (f"{REFUSAL} (A draft answer was withheld because its citations could not be "
                          f"verified against the retrieved passages.)")

        valid, invalid = rag.check_citations(answer, retrieved)
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        model_calls = 0
        for m in state["messages"]:
            if isinstance(m, AIMessage):
                model_calls += 1
                for k in usage:
                    usage[k] += (m.usage_metadata or {}).get(k, 0)
        return {
            "question": question, "answer": answer, "refused": is_refusal(answer),
            "citations": valid, "invalid_citations": invalid,
            "searches": [c["args"].get("query", "") for m in state["messages"] if isinstance(m, AIMessage)
                         for c in m.tool_calls if c["name"] == "search"],
            "retrieved": [f"[{s} | {l}]" for s, l in retrieved],
            "retrieved_text": "\n\n".join(text_of(m) for m in state["messages"]
                                          if isinstance(m, ToolMessage) and m.name == "search"),
            "guardrail_events": events, "model_calls": model_calls, **usage,
            "seconds": round(time.time() - started, 2), "model": self.model_name,
        }

    @staticmethod
    def _answer(state: dict) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and not last.tool_calls and text_of(last).strip():
            return text_of(last).strip()
        return f"{REFUSAL} (The agent stopped at its call limit before answering.)"

    @staticmethod
    def _retrieved(state: dict) -> list[tuple[str, str]]:
        labels = []
        for m in state["messages"]:
            if isinstance(m, ToolMessage) and m.name == "search":
                labels += rag.retrieved_labels(text_of(m))
        return list(dict.fromkeys(labels))

    @staticmethod
    def _citation_problem(answer: str, retrieved: list) -> str | None:
        valid, invalid = rag.check_citations(answer, retrieved)
        if invalid:
            return f"these citations do not match any retrieved passage: {', '.join(invalid)}."
        if not valid and not is_refusal(answer):
            return "it makes claims without citing any retrieved passage."
        return None


def print_result(r: dict) -> None:
    print(r["answer"])
    if r["citations"]:
        print("\nCitations checked against the retrieved passages:")
        for c in dict.fromkeys(r["citations"]):
            print(f"  ✓ {c}")
    for e in r["guardrail_events"]:
        if e["guardrail"] == "approval":
            print(f"\n(Approval: {e['tool']}({e['args']}) was {'APPROVED' if e['approved'] else 'REJECTED'} by the human.)")
    fired = [e for e in r["guardrail_events"] if e["guardrail"] == "citations"]
    if fired:
        print(f"\n(Citation guardrail fired {len(fired)} time(s): {fired[0]['problem']})")
    print(f"\n[{r['model']} · {r['model_calls']} model calls · {len(r['searches'])} searches · "
          f"{r['total_tokens']} tokens · {r['seconds']} s]")


async def main(question: str) -> None:
    async with Harness() as harness:
        print_result(await harness.ask(question))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('usage: python agent.py "your question"')
    asyncio.run(main(" ".join(sys.argv[1:])))
