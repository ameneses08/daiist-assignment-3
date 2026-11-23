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
