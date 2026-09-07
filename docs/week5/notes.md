# Week 5 error analysis — notes

Supporting evidence for [`taxonomy.md`](taxonomy.md). Trace file, seeded draw,
replay, open coding, clustering, prediction, benchmark note, bonus.

---

## 0. What was run, and against what

| | |
| --- | --- |
| Traces | 148 through the shipped pipeline, real Groq key, 2026-09-07 |
| Trace file | `docs/week5/traces.jsonl`, sha256 `61f4e963…a133133` |
| Corpus | 7 articles, 30 chunks, `heading/1000/100`, fingerprint `6011b16fe1358dd4` |
| Embedder / reranker | `all-MiniLM-L6-v2` / `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Model | `openai/gpt-oss-120b`, temperature 0, max_tokens 400 |
| Prompt | `v1-cfc04156c4e7` |
| Median latency | 6.5 s end to end |
| App commit at run time | `a88ee38` |

**Where the traffic came from.** 120 support tickets in
`backend/eval/week5/ticket_bank.jsonl`, plus the 14 curated demo questions the
chat UI offers, plus 14 unscoped controls of those same demo questions. Every
ticket produced a trace; none were dropped, and none errored.

**The traffic mix**, drawn by seeded content-blind assignment rather than
written into the bank, so no question was hand-paired with a configuration:

| dimension | drawn |
| --- | --- |
| mode | week4 94, week3 26 |
| top_k | 5 → 81, 3 → 21, 8 → 13, 10 → 5 |
| filters | none 100, product area or document 20 |

### 0.1 The authoring protocol, and its honest limits

The questions are synthetic. The traces are not. To keep the synthetic half from
deciding the answer in advance:

1. The bucket quotas were fixed before a single question was written, and they
   describe **how customers write** — typo, fragment, compound, follow-up
   lacking context — never how retrieval fails. The mapping between those two
   vocabularies is many-to-many, and it is exactly what the traces reveal.
2. Questions were written from each article's **heading list**, never its body
   text. Writing a question after reading the sentence that answers it produces
   lexical shadowing that flatters retrieval.
3. The pipeline was never run during authoring. Not once, not for a spot check.
4. Ticket ids were assigned after a seeded shuffle, so `T001…T120` does not run
   bucket by bucket and reading traces in id order hands the coder nothing.
5. The fixture schema is four keys and cannot hold a label. There is no expected
   chunk, no article id, no category.
   `test_no_ticket_carries_an_expected_answer_or_a_failure_label` enforces that.
6. The bank was committed at `38ab685`, **before the tracing module existed at
   all** — at that commit the app was physically incapable of producing a trace.
   `test_the_ticket_bank_was_committed_before_any_tracing_code_existed` checks
   this against `git log` rather than taking my word for it.

Two limits worth stating rather than burying. First, I knew the corpus contains
a set of near-duplicate legacy plan packs, because `CLAUDE.md` documents them as
a deliberate fixture; so the plan-name-confusion bucket was written knowing the
collision exists in the *corpus*. What was not known, and could not be until the
traces existed, is whether the app fails on it, or how. Second, these rules
remove the specific bias the brief names. They do not remove domain familiarity,
and nothing can.

---

## 1. The seeded sample — 20 random traces

### 1.1 The draw

```
ids = sorted(t["trace_id"] for t in traces if t["pool"] == "random")
rng = random.Random(f"{seed}:{pool}")     # seed = 20260907
picked = sorted(rng.sample(ids, 20))
```

Three properties are deliberate. **Ids are sorted before sampling**, because
`random.sample` depends on the order of the population it is handed, and a
resumed collection run that reordered lines would otherwise silently move the
sample. **Each pool has its own stream**, `"{seed}:random"` and `"{seed}:demo"`,
so drawing the bonus 10 cannot perturb the 20 already quoted in the taxonomy.
**The result is pinned** to the trace file's sha256 in `sample.json`, so
regenerating the traces breaks loudly instead of the sample quietly describing a
file that no longer exists.

### 1.2 Seed and command

```bash
cd backend
python scripts/sample_traces.py --seed 20260907 --n 20 --demo-n 10 --markdown
```

Seed **20260907**. Trace file sha256
`61f4e9637ddcf089f23a739f070c0c74bd1d15b7f4ef4ae346a10ae20a133133`.
Re-running the command reproduces both lists exactly;
`test_the_sampler_is_reproducible_under_its_own_published_seed` re-derives them
from the published seed and asserts they match.

### 1.3 The 20 traces

| trace_id | ticket | mode | top_k | filter | question |
| --- | --- | --- | ---: | --- | --- |
| `TR-0012` | T012 | week4 | 5 | policies/account_management.md | What is the difference between the 599 and 1999 plans and which one includes the OTT bundle? |
| `TR-0023` | T023 | week4 | 3 | - | Is GST included in the 1199 price or added on top? |
| `TR-0026` | T026 | week4 | 5 | - | AF401 eror |
| `TR-0035` | T035 | week4 | 5 | - | How long is installation, is it free, and do I need to be at home for it? |
| `TR-0037` | T037 | week4 | 5 | - | Can I suspend my connection for two months, will I still be charged, and does my plan validity extend? |
| `TR-0045` | T045 | week4 | 3 | - | I am in Chennai, can I get AirFiber_1299_1M? |
| `TR-0055` | T055 | week4 | 8 | installation | how much is that? |
| `TR-0060` | T060 | week4 | 5 | - | Are legacy plans cheaper than the current ones? |
| `TR-0071` | T071 | week4 | 3 | - | changng account holdr documents |
| `TR-0072` | T072 | week4 | 5 | - | Look, I am not trying to be difficult, but I have now been told three different things by three different people... |
| `TR-0073` | T073 | week3 | 10 | - | My box has an orange light that is not flashing, what does that mean? |
| `TR-0077` | T077 | week4 | 5 | - | Is AirFiber_999_1M still available for new customers? |
| `TR-0084` | T084 | week4 | 5 | - | 500 |
| `TR-0089` | T089 | week4 | 5 | - | How do I reset my Gmail password? |
| `TR-0090` | T090 | week4 | 5 | - | what if I don't? |
| `TR-0098` | T098 | week4 | 5 | - | How high above the floor should the mesh extender be placed? |
| `TR-0111` | T111 | week4 | 5 | policies/refund_policy.txt | I want to move to a bigger pack mid-month, will I be charged the full amount? |
| `TR-0112` | T112 | week4 | 3 | - | I have been on AirFiber_999_1M since 2024, is it still valid? |
| `TR-0114` | T114 | week4 | 5 | - | Do you offer a landline bundle? |
| `TR-0115` | T115 | week4 | 3 | - | Where should I put the second wifi box for best coverage? |

Two of the twenty carry a filter that does not match the question, and one
carries a product area that does not. That is the content-blind draw doing its
job: a real user who set a document filter two messages ago and then asked about
something else produces exactly this, and I did not get to choose which
questions it happened to.

---

## 2. Replay of one trace, from the trace alone

Full side-by-side output: [`replay.md`](replay.md).

### 2.1 The seeded pick

```bash
python scripts/replay_trace.py --from sample --pick-seed 20260907 --out ../docs/week5/replay.md
# random.Random("20260907:replay").choice(sorted(sample["random"]))  ->  TR-0023
```

Pick seed **20260907**, drawn from the sampled 20 rather than chosen. It landed
on `TR-0023`, *"Is GST included in the 1199 price or added on top?"*

### 2.2 Original vs replayed

The script rebuilt the index from the configuration recorded in the trace,
checked the corpus fingerprint, re-ran retrieval, and re-sent the recorded
prompt to the recorded model at the recorded parameters.

| field | result |
| --- | --- |
| corpus fingerprint | match (`6011b16fe1358dd4`) |
| retrieval ranking, all 3 chunks | match |
| dense and rerank scores, 4 dp | match |
| gate score `0.3401`, refused `False` | match |
| chunk text re-derived and sha256-checked | match |
| raw model output | match, byte for byte |

Both the original and the replay answered *"I don't know based on the provided
documents."* — which is itself the interesting part, and is discussed at
`TR-0023` in section 3.

### 2.3 Fields I had to add

The chat response returns an answer, a source list with scores, and a small
retrieval summary. Everything below had to be added to make a trace replayable,
and every one of them is now written by the app rather than by the harness:

| field | why replay needs it |
| --- | --- |
| `trace_id` | the API returned no request identifier of any kind |
| `started_at`, `latency_ms` | no timestamp and no timing existed anywhere |
| `generation.system_prompt`, `user_prompt` | the response never carried the prompt; it is `format_citation` interleaved with chunk text, and reconstructing it would drift the moment that function changed |
| `generation.prompt_id` | so a trace says which prompt produced it; hash-derived, so an edit cannot silently relabel old traces |
| `generation.raw_output` | two of the three exits replace the model's words with a refusal string it never wrote |
| `generation.model`, `params`, `usage`, `finish_reason` | model and parameters were nowhere in the response |
| **`temperature`** | **the important one.** The shipped app sends no temperature, so Groq uses its own default and the same prompt returns differently worded text on every call. A genuine production trace is therefore *not* byte-replayable. Pinning it to 0 for the collection run was the precondition for this entire deliverable |
| `config.chunk_strategy/size/overlap` | chunk ids are positional and meaningless without them |
| `config.corpus.fingerprint`, per-chunk `text_sha256` | `backend/data/docs/` is gitignored, so without these a replay against a moved corpus produces a plausible-looking but meaningless diff |
| `answer.source` | names which of the three exits fired |

### 2.4 What I could not reconstruct

Three things, stated with their consequence rather than glossed:

1. **Replay from the trace's source list alone is impossible.** The response
   carries a 180-character preview per chunk, and all 3 retrieved chunks in
   `TR-0023` are longer than their preview. The prompt is recoverable only
   because it is stored whole, separately. The fallback — re-deriving chunk text
   from the corpus and checking each recorded sha256 — worked, but it needs the
   corpus, so it is not "from the trace alone".
2. **Which refusal layer fired is inferred, not recorded, for the pre-LLM
   gate.** `answer.source` records it now, but it is derived inside `ask` from
   the capture dict rather than reported by `answer_with_groq` itself. If that
   function grew a fourth exit, the trace would mislabel it and nothing would
   fail.
3. **Nothing identifies the user or the session.** Every trace is a standalone
   request. For the follow-up questions in the sample — `TR-0090`, *"what if I
   don't?"* — there is no way to recover what was asked before it, because the
   app has no conversation history to record. That is a property of the app, not
   of the trace format, and it is why those traces can only be coded on what the
   app saw.

---

## 3. Open coding — 20 sentences, one per trace

One sentence per trace, describing what was seen in that trace. Not what
category it belongs to, not what caused it, and not what to change. Written
against the trace records only, in the order the seeded draw produced.

1. `TR-0012` — The document filter was pinned to the account-management policy while the question asked about two plans, so only account-management chunks came back, and the answer was "I don't know based on the provided documents." followed by "(Source: policies/account_management.md)".
2. `TR-0023` — Three plan chunks came back scoring between 0.31 and 0.34 against a 0.15 threshold, none of them mentions tax anywhere, and the answer was "I don't know based on the provided documents."
3. `TR-0026` — The question arrived as "AF401 eror" with no hyphen and a misspelling, and the answer returned the AF-401 meaning, its resolution step and its escalation count from the error-code table.
4. `TR-0035` — The ticket asked three things and the answer covered installation time and cost for two plans, then stopped in the middle of the word "AirFiber" inside a source line, never reaching whether the customer must be at home.
5. `TR-0037` — The ticket asked three things and the answer addressed all three including the postpaid case, and the sentence about postpaid accounts not being pausable does appear in the chunk it cited.
6. `TR-0045` — The answer said the 1299 pack is sold only in Hyderabad and so is unavailable in Chennai, and it rendered the citation as 【help_centre/airfiber_legacy_plans.md】 rather than the source line every other answer in the sample used.
7. `TR-0055` — The follow-up "how much is that?" arrived with no prior turn to resolve it, the top-ranked chunk was the installation-timelines section that names the ₹500 charge, and the request was refused at a score of 0.1414 without the model being called at all.
8. `TR-0060` — Five legacy-plan chunks came back, none of the legacy plan sections states a price anywhere in the article, and the answer was "I don't know based on the provided documents."
9. `TR-0071` — The question arrived as "changng account holdr documents", the closing-the-account chunk was ranked first and the account-holder chunk second, and the answer listed the transfer form, the photo ID, the nil-balance condition and the three-working-day timeline.
10. `TR-0072` — A long complaint ended in "which plan I am actually on and what it costs", the migration-rules chunk was ranked first, and the answer was "I don't know based on the provided documents." with no mention of the migration rules that were sitting in front of it.
11. `TR-0073` — "orange light that is not flashing" returned the LED status table first under week3 at top_k 10, and the answer gave the solid-orange row's meaning and its power-cycle step.
12. `TR-0077` — The answer said the 999 pack has been closed to new customers since 1 January 2026, and it again rendered the citation as 【help_centre/airfiber_legacy_plans.md】.
13. `TR-0084` — The single token "500" returned both chunks that name a ₹500 charge at ranks one and two, and the request was refused at a score of 0.1289 without the model being called.
14. `TR-0089` — A question about a Gmail password scored 0.188, cleared the 0.15 threshold, reached the model, and came back "I don't know based on the provided documents."
15. `TR-0090` — The follow-up "what if I don't?" arrived with no prior turn, the five chunks returned scored between 0.01 and 0.10, and the request was refused without the model being called.
16. `TR-0098` — The mesh-extender placement chunk came back first at 0.6353 and the answer gave the "at least 1 metre above the floor" figure and named its source file.
17. `TR-0111` — The document filter was pinned to the refund policy while the question asked about a mid-cycle upgrade, exactly one chunk came back, and the answer was "I don't know based on the provided documents." followed by "(Source: policies/refund_policy.txt)".
18. `TR-0112` — The customer said they had been on the 999 pack since 2024, the three chunks returned were legacy plan descriptions that do not carry the article's opening sentence about existing subscribers keeping their packs, and the answer was "I don't know based on the provided documents. (Source: help_centre/airfiber_legacy_plans.md)".
19. `TR-0114` — A question about a landline bundle returned five plan chunks scoring between 0.31 and 0.35, none of which mentions landlines, and the answer was "I don't know based on the provided documents."
20. `TR-0115` — "second wifi box" returned the official-speed-test chunk first and the mesh-placement chunk second, and the answer gave the halfway placement, the one-metre height and the microwave warning.

### 3.1 Zero code changes during this step

This section was written and committed on its own. The commit touches exactly one
file and that file is markdown:

```
$ git diff --stat e9c2c55..HEAD -- '*.py' '*.ts' '*.tsx'
(no output)

$ git show --stat --oneline HEAD
week5: open coding, 20 traces, one sentence each - no code changes
 docs/week5/notes.md | 41 +++++++++++++++++++++++++++++++++++++++++
```

`test_no_source_file_changed_during_the_open_coding_commit` re-derives the second
command from `git log` and asserts the file list is exactly
`["docs/week5/notes.md"]`, so the claim cannot go stale.
