# Design decisions — log and study guide

One entry per major decision: **what** was decided, **why**, the **trade-off**, and what to be
ready to explain in the written check. Newest decisions at the bottom.
"Proposed by Claude" marks where the AI suggested an option; the choice was mine (see AI use in REPORT.md).

---

## D1 · Use case: GDPR assistant for a small business owner

**What.** The user is a small business owner or startup founder who handles customer data and
asks practical questions: "Do I need consent for my newsletter?", "A laptop with client data was
stolen — do I have to report it, and by when?"

**Why.** It is a use case where a wrong answer costs more than "I don't know":

| Answer | Consequence |
|---|---|
| Wrong ("you don't need to report it") | Missed 72-hour breach deadline, processing without a legal basis → fines (up to €10M / 2% of turnover for breach-notification failures, Art. 83(4)), lost customer trust |
| "I don't know — check with the AEPD or a lawyer" | Costs time and maybe a consultation fee, but no legal harm |

So the system should **prefer refusing over guessing** — this drives the refusal rules, the
evaluation (wrong refusals vs. unsupported claims) and the ship decision.

**Alternatives considered.** Ordinary citizen exercising GDPR rights (fine, but fewer concrete
decisions with deadlines); Spanish student residence permits (more original, but Spanish texts and
cross-language retrieval risk); university's own rules (licence not clear).

**Be ready to explain.** Why "I don't know" is the *safe* failure here, and how that shapes everything downstream.

---

## D2 · Corpus: GDPR articles + two EDPB guidelines

| Document | Source id | Words |
|---|---|---|
| Regulation (EU) 2016/679 — GDPR, 99 articles | `GDPR` | 29,730 |
| EDPB Guidelines 05/2020 on consent (v1.1) | `EDPB 05/2020` | 13,534 |
| EDPB Guidelines 9/2022 on breach notification (v2.0, final) | `EDPB 9/2022` | 13,693 |
| **Total** | 3 documents | **56,957** |

**Why these.** The law itself plus the official guidance that explains it, on the two topics a
small business most often gets wrong (consent and breaches). Guidelines give worked examples, which
is what a non-lawyer needs; pairs like "GDPR Art. 33 + EDPB para. 29" make natural two-passage questions.

**Licences.** EU legal acts: reuse authorised (Commission Decision 2011/833/EU), acknowledge the
source. EDPB: reuse authorised for commercial and non-commercial purposes, acknowledge the source,
don't alter the meaning. No personal data (examples in the guidelines are fictional).

**Why the final v2.0 breach guidelines, not v1.0.** v1.0 (Oct 2022) was the consultation draft.
Using the adopted version avoids answering from superseded text.

**Be ready to explain.** Licence conditions; why official guidance and not blogs; that the corpus
has a date (GDPR amendments — the "Digital Omnibus" — were proposed in Nov 2025 and are not yet
law), so answers are only as current as the documents.

---

## D3 · GDPR recitals left out

**What.** Only the 99 articles are indexed, not the 173 recitals ("whereas…" paragraphs).

**Why.** Budget: recitals add ~24,000 words ≈ 160 more chunks *per design*. Two designs would
need ~1,180 embeddings, over the ~1,000/day free tier.

**Trade-off.** Recitals explain the intent of articles (e.g. Recital 32 on what counts as clear
consent). Without them some "why" questions lose context — but the EDPB guidelines quote the
important recitals, so most of that context is still in the corpus.

**Be ready to explain.** The embedding budget as a real design constraint.

---

## D4 · Held-back document for the add-document test: EDPB Guidelines 07/2020 (controller vs processor)

**What.** Not in the main corpus. Later added through the `add_document` tool to show an
unanswerable question becoming answerable.

**Why.** Its topic (who is controller, processor or joint controller) is close to the corpus but
not covered in depth, so it can answer a realistic question that the corpus cannot.

---

## D5 · GDPR text from the EU Publications Office as HTML, not a PDF

**What.** `index.py` fetches the Official Journal text from the Publications Office
(EUR-Lex blocks scripted downloads; same official text).

**Why.** The HTML marks every article and paragraph in its tags (`art_33`, `033.001`), so
locations like `Art. 33(1)` come straight from the document's own structure — no guessing from
PDF layout.

---

## D6 · PDF extraction with pdfplumber, cleaned by font size

**What.** EDPB PDFs are read line by line with their font size:
body = 11 pt, headings = 12/13/16 pt, footnotes = 10 pt, footnote markers = 7 pt.

**Problems fixed** (one goes in REPORT.md as "an extraction problem I fixed"):
1. **Footnotes mixed into the text** and markers glued to words ("unlawful.3") → dropped by font size.
2. **Words glued or split** ("ofthe", "madedependenton", "dat a") → tighter character spacing
   (`x_tolerance=1`) plus a small rule that rejoins split words found elsewhere in the same document.
3. **Annex B table of 10 breach examples scrambled** (plain extraction interleaves the 4 columns)
   → read as a table, each cell assigned to its column by x-position, rows continued across pages.
   This table is the most useful part for a small business ("ransomware", "email sent to wrong list").
   Two follow-up bugs found by testing search: a row continued on the next page was cut off
   (fixed by building each example's text only after all pages are read), and merged examples had
   no label in their text (fixed: each example is its own chunk, starting "Example iv: …", so it
   can be cited as `[EDPB 9/2022 | Annex ex. iv]`).
4. Page footers ("Adopted 7"), tables of contents and the title/preamble pages removed.

**Why pdfplumber over pypdf.** pypdf reported wrong font sizes for the consent PDF, so footnotes
couldn't be separated reliably; pdfplumber gives each character's size and position.

**Noticed, not a bug.** Consent guidelines para. 152 is empty in the original PDF.

---

## D7 · Location metadata on every chunk

**What.** Each chunk stores `source`, `location` (e.g. `Art. 33(1)–(4)`, `para. 29–31`,
`Annex ex. vi`), `page` (EDPB), `section` (heading path) and `locs` (every location it covers).

**Why.** Three uses: the citation the user sees `[GDPR | Art. 33(1)]`; the hit-rate check
(did retrieval find the expected location?); and the code check that a citation in an answer
points to a passage that was really retrieved.

---

## D8 · Embeddings: gemini-embedding-2, 768 dimensions, task prefixes

**What.** Each chunk is embedded as `title: <heading> | text: <chunk>`; each query as
`task: question answering | query: <question>`. Vectors have 768 dimensions.

**Why.**
- `gemini-embedding-2` takes the task as a text prefix (it has no `task_type` setting);
  documents and questions get different prefixes because a question doesn't look like the passage
  that answers it.
- 768 instead of the default 3,072: 4× smaller index (limit 90 MB), and the model is trained so
  shorter vectors keep most of the quality.
- Gotcha: passing a plain list of texts returns **one combined** vector; each text must be wrapped separately.

---

## D9 · Never pay twice for an embedding

**What.** Chunk ids are hashes of their content; a chunk whose id is already stored is never
re-embedded. Vectors are saved after every batch of 20. Query vectors are cached in
`index/query_cache.json`. A daily-quota error stops cleanly; a per-minute limit (HTTP 429) waits and retries.

**Why.** ~1,000 embeddings/day. A crash, a re-run or the grader running `main.py index` costs nothing.

---

## D10 · Storage: ChromaDB in `index/`, one collection per design

**Why.** Persistent, committed to git, loaded by the server at startup without re-embedding.
One collection per design makes the comparison clean: same questions, same query vectors, different chunks.

---

## D11 · Retrieval designs to compare  *(confirmed 23 Nov)*

| | A · `fixed` | B · `structure` | C · `structure` + keyword (hybrid) |
|---|---|---|---|
| **How** | 200-word windows, 25-word overlap, ignores structure | One chunk per article paragraph / numbered paragraph; neighbours in the same article or section merged up to 250 words; >350 words split; embedded with its heading path | B's chunks, ranked by vector search **and** BM25 keyword search, merged with reciprocal rank fusion |
| **Chunks** | 327 | 343 | 343 (no new embeddings) |
| **Pros** | Simple; even sizes; works on any document; overlap softens cuts | Chunks match what people cite → precise citations; heading adds context ("Notification of a personal data breach"); one idea per chunk | Exact terms ("Article 33", "72 hours", "cookie wall") are where embeddings are weakest; free to try |
| **Cons** | Cuts mid-sentence and across articles → vaguer citations ("Art. 32(4)–Art. 33(2)"); no heading context | Uneven sizes (17–333 words): tiny chunks carry little meaning; depends on parsing each document's structure | Common legal words add noise; one more parameter (fusion constant) |

**Honest caveat for the report.** A and B differ in two ways at once (boundaries *and* heading
in the embedding), so if B wins we can't say which of the two caused it.

**Decision rule.** Choose by hit rate @1/@3/@5 on my test set; a tie goes to the design with
fewer words in the prompt (cheaper, less noise).

**Status.** Both designs indexed on 23 Nov: `corpus_fixed` 327 chunks, `corpus_structure` 343
chunks, 670 embeddings in total (index/ = 12 MB). The hybrid variant reuses `corpus_structure`.

---

## D12 · MCP tools: what `search` and `add_document` do  *(add-document policy: to confirm)*

**`search(query)`** returns the 5 best passages, each headed by its citation `[source | location]`,
the document, page and section. Only a `query` argument — no source filter the model could
misuse to hide relevant passages. It uses the design chosen by the hit-rate numbers (D11).

**`add_document(path)`** imports `index.py`'s own pipeline (`chunk_file`, `embed_and_store`) —
the server never has a second copy of the chunking logic.

**When the document is already indexed** (my policy):

| Situation | What happens | Why |
|---|---|---|
| Same file, same content | Skipped, 0 embeddings | Re-adding must not waste quota or duplicate passages (duplicates would crowd out other results) |
| Same name, changed content (e.g. a new version) | Replaced: changed chunks embedded, removed passages deleted | Answers must not mix the old and the new version |
| New file | Added | |

**Tool descriptions matter.** The docstring is all the model sees, so it says what the corpus
covers, when to search again with other words, the citation format, and that `add_document`
changes the index for everyone (only when the user asks).

---

## D13 · AGENTS.md: the assistant's rules  *(draft by Claude — mine to review and edit)*

Ten rules, each with its reason. The core four: **search before every answer**; **answer only
from retrieved passages**; **cite every claim** with the exact `[source | location]` label;
**refuse with a fixed sentence** — "I can't answer this from the documents I have." — plus where
to ask (AEPD or a lawyer) when the passages don't answer.

**Why a fixed refusal sentence.** Code can then count refusals exactly (correct refusal on an
unanswerable question vs. wrong refusal on an answerable one) without an LLM judging it.

**Why "search again before refusing" (up to 3 searches).** Refusing too early is also a failure
(a *wrong refusal*); a second search with other words often finds the passage.

**Why list out-of-scope topics** (national law, the Digital Omnibus, specific companies' fines).
Those are where a model is most tempted to answer from memory.

---

## D14 · Agent model: `gemini-3-flash-preview`

**Why.** `gemini-2.5-flash` is no longer available to new keys. Google's suggested replacement
`gemini-3.8-flash` was overloaded on 23 Nov (503 errors; the agent hung on retries) and
`gemini-3.5-flash` took 25 s for a one-word reply; `gemini-3-flash-preview` answered in ~1 s.
Default temperature (Google advises not lowering it for Gemini 3).

**Trade-off.** A "preview" model may change or be retired; the model name is recorded with every
answer in the evaluation results, so results stay traceable.

---

## D15 · Harness guardrails (agent.py)

| Guardrail | How | Why |
|---|---|---|
| **Approval before `add_document`** | LangChain `HumanInTheLoopMiddleware`; asks "Approve? [y/N]" on the terminal; with no terminal (evaluation, check.py) it rejects | Adding a document changes every later answer and spends quota — a human decides |
| **Call limits** | ≤ 4 tool calls and ≤ 8 model calls per question | Stops loops; caps cost per question |
| **Citation check** (my extra guardrail) | Every `[source \| location]` must lie inside a passage search actually returned, and a non-refusal must cite something. One chance to fix; then the answer is withheld and replaced by the refusal | Directly targets the costly failure — a confident claim with no support. Code can check it exactly, no LLM needed |

**It fired on the first test** (`eval/examples/guardrail_citation_fired.txt`): the draft cited
`[GDPR | Art. 33(5)]` (record-keeping), but search had only returned Art. 33(1)–(4). The model
was told, rewrote the answer with valid citations, and passed. **Limit:** it checks that the
cited passage was retrieved, not that it says what the claim says — that's the judge's job (D-eval).

---

## D16 · MCP tools reach the agent through a small bridge, not `langchain-mcp-adapters`

**Why.** `langchain-mcp-adapters` 0.3.1 is incompatible with `mcp` 2.3 (import error), and `mcp`
2.3 is what `check.py` and the server use. ~15 lines in `agent.py` start `server.py` over stdio,
list its tools and wrap each as a LangChain tool — the agent uses the same server as the editor.

---

## D17 · LLM judge: model and rubric (strict "correct")

**Judge model:** `gemini-3.5-flash` — a *different* model from the agent (`gemini-3-flash-preview`),
so the judge is not grading its own style. Pro models are not on the free tier (quota error);
3.5-flash is slow (~30 s per call) but that only matters for a batch run.

**Rubric** (the judge sees the question, my reference answer, the retrieved passages and the answer):

| Score | 1 when… | 0 when… |
|---|---|---|
| **Correct** (vs my reference) | Same conclusion (yes/no, deadline, who to notify) **and every condition, exception and element my reference lists**, nothing contradicted | Different conclusion, a wrong number/party, or **any** listed condition/exception missing |
| **Supported** (vs retrieved text, not reality) | Every factual claim is in or follows directly from the retrieved passages | Any claim not in the passages — even if it is true. The judge lists them |

**Why strict.** For a small business a missed exception is a missed obligation (e.g. "notify
within 72 h" without "…unless unlikely to result in a risk" leads to over- or under-reporting).
**Consequence:** my reference answers must list exactly the conditions that matter — no more,
or the judge will fail good answers.

**Refusals are graded by code**, not by the judge: refusal on an unanswerable question = correct;
on an answerable one = wrong refusal.

**Why "supported" is judged against the retrieved text, not the truth.** It measures whether the
system makes things up. A true-but-unretrieved claim is still a failure of grounding — the user
can't verify it.

---

## D18 · Retrieval design chosen: **B · structure-based chunks, vector search**

Hit rate on my 20 answerable questions (final run 23 Nov, with the final expected locations;
`eval/retrieval_summary.csv`):

| Design | hit@1 | hit@3 | hit@5 | both passages found @5 (multi) | MRR@5 | words added to prompt (top 5) |
|---|---|---|---|---|---|---|
| A · fixed, vector | 0.55 | 0.85 | **0.90** | 0.50 | 0.688 | 1,000 |
| **B · structure, vector** | **0.70** | 0.85 | 0.85 | **0.583** | **0.767** | **906** |
| C · structure + hybrid | 0.30 | 0.55 | 0.65 | 0.417 | 0.433 | 921 |
| A · fixed + hybrid | 0.30 | 0.55 | 0.75 | 0.333 | 0.464 | 1,000 |

(A first run, before I corrected some expected locations, had A at 0.70/0.85 for hit@3/@5 — the
locations, not the system, changed.)

**Why B, although A finds one more question in the top 5.** B wins where it matters most for
an agent that reads the top results: rank 1 (+15 points = 3 questions), MRR (0.767 vs 0.688),
finding *both* passages for two-passage questions (0.583 vs 0.50), and it puts ~10% fewer words
into the prompt. hit@3 is a tie. A's edge at hit@5 is a single question. By my rule (D11) —
highest hit rates, ties to the cheaper design — B is the better trade.

**Surprise: hybrid (keyword) search made things worse** for both chunkings. Likely reason:
my questions are written like a real user ("I run a small business… my customers…"), so the
keyword side matches filler words (business, customer, data) that appear everywhere, and the
fusion gives that weak ranking equal weight, pushing good vector hits down. Keyword search
helps with exact terms ("Article 33"), which my users rarely type.

**Caveats to state in the report.** Only 20 answerable questions, so one question = 5 points;
the differences between A and B are 1–3 questions. A and B differ in two ways (boundaries and
heading in the embedding), so the win can't be pinned on one of them. 3 of 20 questions are not
in B's top 5: candidates for "retrieval miss" in the failure analysis.

**Changed:** `rag.ACTIVE_METHOD = "vector"` (was "hybrid") — the server and agent use B.

---

## D19 · Models switched to "lite" because of free-tier daily limits

**What happened.** The first full evaluation stopped after 6 questions: `gemini-3-flash-preview`
allows only **20 requests per day** on the free tier, and each question takes 2–5 model calls.
The judge (`gemini-3.5-flash`) was overloaded (503) at the same time; the 3.6–3.8 flash models too.

**Now:** agent = `gemini-3.5-flash-lite`, judge = `gemini-3.1-flash-lite` — still two
*different* models, each with its own quota, and both answer in ~1 s. A test question took
2 model calls, 1 search, 3 s, ~4,800 tokens, with all citations valid.

**Trade-off.** Lite models are weaker: the agent may follow AGENTS.md less faithfully, and a
weaker judge agrees less with a human — which is exactly what my 20+ own grades measure.
All 30 questions are re-asked with the new model (answers from two models are never mixed).

**Lesson for the report.** Cost per question isn't only tokens and seconds: on a free tier
the binding limit is *requests per day per model*, so an agent's number of model calls per
question decides how many users it can serve. Also fixed: failed answers are no longer reused,
errors are shown as errors, and a daily-quota error stops the run cleanly.
