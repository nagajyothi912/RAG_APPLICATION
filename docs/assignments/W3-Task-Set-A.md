<!-- Soft Suave · The AI Engineering League -->
# Week 3 Practical — Task Set A

## Ingest the new help-centre drop and prove your chunking finds the answer

| | |
|---|---|
| Domain | Customer support tickets |
| Week | 3 — Retrieval-Augmented Generation, From Parts |
| Module | M2 — Retrieval & RAG |
| Sat on | Week 4 · Monday |
| Marks | 100 |

> **This is an extension of the app you already built in Week 3.** It is not a build from scratch, and it tests only this week's concepts. Bring your numbers written down.

---

## 1. Problem statement

Support has just published a batch of 6 new help-centre articles covering the billing migration, and every one of them is half troubleshooting tables (error code, cause, fix) and half prose. Your RAG app already indexes the old articles, but nobody knows whether your current chunker survives a table with an ERR-4032 row in it. Work against your existing pipeline: ingest the drop, measure two chunking strategies on questions you already know the answers to, and make the app refuse what it cannot source.

---

## 2. Requirements

1. Ingest the 6 supplied articles into your existing index with metadata on every chunk: source_file, article_id, product_area, last_updated. A chunk with no source_file is a failed ingest.
2. Write 8 questions whose answers you already know and can point to by article and section (at least 3 must depend on a row inside a troubleshooting table, e.g. what ERR-4032 means and what the fix is).
3. Index the same 6 articles under TWO chunking strategies — your current one, and a structure-aware one that never separates a table row from its header row. Run all 8 questions search-only against both and report hit-in-top-5 as a number out of 8 for each. Two strategies, two numbers, same 8 questions.
4. Add a metadata filter on product_area and show one query where filtering changes the top-1 result. Paste both result lists (unfiltered and filtered) with scores.
5. Run 3 answerable questions through generation with a citation per claim that resolves to a real chunk_id and article, and 3 questions your corpus cannot answer (e.g. a refund SLA that appears nowhere) that must be refused rather than invented.
6. Time reality: do NOT re-index your whole historical corpus. Index the 6 new articles only, and say so in your write-up.

---

## 3. Expected output

A results.md containing: the 8 questions with their known-correct article/section, a table of hit-in-top-5 for both chunking strategies (X/8 each), the unfiltered vs filtered result lists for one query, 3 cited answers with clickable/resolvable chunk_ids, 3 refusal transcripts, and one paragraph naming which chunking strategy you are keeping and why. Plus the code diff and the search-only dump for all 8 questions under both strategies.

---

## 4. Evaluation rubric

| Criterion | Points |
|---|---|
| Two hit-in-top-5 numbers over the SAME 8 known-answer questions, per-question record shown, not a summary claim | 30 |
| Metadata filter demonstrably changing retrieval, with both result lists and scores pasted | 20 |
| Citations resolve to real chunk_ids and the cited chunk actually contains the claim (grader will check one) | 20 |
| All 3 out-of-corpus questions honestly refused, with the refusal transcripts pasted | 20 |
| Written defended chunking choice plus one documented retrieval that embarrassed you, with its diagnosis | 10 |
| **Total** | **100** |

*Zero points for polish, UI, or "it works". This mirrors the House rubric: failure-finding and a number that moved are what score.*

---

## 5. Bonus challenge

Find a question where the structure-aware chunker WINS on retrieval but LOSES on the final answer, because the tight table-row chunk retrieves precisely and then gives the model too little surrounding prose to answer completely. Show both answers side by side and write two sentences on the precision/completeness tension.

---

## 6. Submission checklist

- [ ] results.md with all 8 questions and their known-correct article + section
- [ ] The two hit-in-top-5 numbers (X/8 and Y/8) in one table
- [ ] Unfiltered vs filtered result lists for one product_area query, with scores
- [ ] 3 cited answers + 3 refusal transcripts pasted verbatim
- [ ] Code diff showing the second chunker and the metadata fields
- [ ] One paragraph: which chunker ships, and why

---

## 7. Common mistakes

- **Writing the 8 questions AFTER looking at what retrieval returns — then your hit-rate measures your question-writing, not your chunker. Write the questions from the articles first, then run search.**
- **Changing the chunker AND swapping the embedding model in the same run, then reporting one number — two changes means you learn nothing about which one moved it.**
- **Judging chunking by eyeballing the retrieved text and saying it 'looks better'. Looks-better is not a number and scores zero here.**
- **Letting the grounding prompt say 'if the context is insufficient, use your best judgement' — that sentence is exactly how ERR-4032 gets an invented fix. The refusal must be forced, not suggested.**
- **Re-indexing the entire historical article corpus and running out of time at minute 45 with no measurement at all. The measurement is the deliverable; the ingest is plumbing.**

---

*Set A of 6. Sets A–F are equivalent in difficulty and objectives; only the domain differs.*
