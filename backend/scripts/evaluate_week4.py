"""
Week 4 retrieval evaluation: baseline, one-variable ablations, shipping decision.

This harness answers a different question from `evaluate_retrieval.py`. That
script asks "which chunking configuration should we ship?" and grades a chunk by
whether it *contains the gold answer string*. This one asks "does the retriever
put the one chunk a human labelled as correct into the top 3?" and grades by
exact `chunk_id`, which is the metric the Week 4 assignment specifies.

The two never share a fixture on purpose: `eval/gold_questions.json` drives
sections 1-8 of results.md, `eval/golden_set.jsonl` drives sections 9-14, and
editing one must not move a number in the other.

Exactly one variable per arm
----------------------------
The shipped `week4` mode runs BM25+RRF *and* cross-encoder reranking. That is
two changes, so it cannot be used to attribute an improvement to either. This
script runs three arms that each differ from the baseline by a single retrieval
change:

    A  baseline   dense cosine only                      (VectorStore.search)
    B  +bm25      BM25 + RRF, no reranker                (use_keyword=True,  rerank=False)
    C  +rerank    cross-encoder over dense, no BM25      (use_keyword=False, rerank=True)

and reports the stacked A+B+C combination separately as a reference point that
is explicitly *not* the one-change candidate.

Why Hit@1 and MRR are reported alongside Hit@3
----------------------------------------------
Hit-rate@3 is the assignment's headline metric, but the corpus is 21 chunks, so
a top-3 window is 14% of the index and the dense baseline saturates it. A metric
that is already at 100% cannot show an improvement or a regression. Hit@1 and
MRR are reported next to it for the same reason Week 3 reports Answer Hit
alongside Article Hit: when the headline number saturates, the decision has to
be made on one that still discriminates. The failure inspection in section 11
falls back to rank-1 failures when @3 produces none.

Latency
-------
Retrieval latency only - no LLM call. Each query is timed `LATENCY_REPEATS`
times after a warm-up pass and the median of those repeats is that query's
latency; p50 is the median across the 12 per-query medians. The reranker is
loaded before timing starts so the first query does not absorb a ~90MB model
download.

Generation failures (G)
-----------------------
A miss is only a retrieval failure if the correct chunk was absent from the top
3. To separate R from G the harness asks the real LLM, on the baseline arm, with
the same prompt the app uses, and checks whether the gold facts appear. Without
a Groq key that column is reported as "not measured" rather than guessed.

Grading that answer is a two-stage check, and the second stage is not optional.
A plain substring test over free-form prose produces false G failures at an
alarming rate: the model writes "R2,500" for the gold "2500", "5-day" with a
Unicode non-breaking hyphen, and "the MAC address isn't whitelisted" for "MAC
address not whitelisted". On the first run of this harness that test flagged 7
of 12 answers as generation failures when all 12 were factually correct. So a
substring hit is accepted as correct immediately, and anything it rejects goes
to an LLM judge that is shown the question, the gold facts, and the answer, and
asked whether the answer states those facts. Only a judge rejection is recorded
as G. Marking a correct answer as a generation failure would corrupt the failure
tally that the whole shipping decision rests on.

Writes sections 9-14 of ../results.md between the week4 markers, leaving the
Week 3 sections above them untouched.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

# Pin the documented configuration before app.config is imported, so a stale
# developer .env cannot silently move the numbers in the report.
os.environ["CHUNK_STRATEGY"] = "heading"
os.environ["CHUNK_SIZE"] = "1000"
os.environ["CHUNK_OVERLAP"] = "100"

from app.services.rag_service import (  # noqa: E402
    Chunk,
    VectorStore,
    answer_with_groq,
    build_chunks,
)
from app.services.retrieval import BM25_AVAILABLE, RERANK_MODEL_NAME, get_reranker  # noqa: E402

CORPUS = ROOT / "sample_documents"
GOLDEN_SET = BACKEND / "eval" / "golden_set.jsonl"
RESULTS = ROOT / "results.md"

STRATEGY, CHUNK_SIZE, OVERLAP = "heading", 1000, 100
TOP_K = 3
LATENCY_REPEATS = 15
MARK_START = "<!-- week4:start -->"
MARK_END = "<!-- week4:end -->"


def _normalise(text: str) -> str:
    """
    Fold the formatting differences that make a raw substring test unreliable:
    every Unicode dash variant to '-', digit group separators removed, and any
    run of non-alphanumerics collapsed to a single space.
    """
    lowered = text.lower()
    for dash in "‐‑‒–—−":
        lowered = lowered.replace(dash, "-")
    lowered = re.sub(r"(?<=\d),(?=\d)", "", lowered)
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _plural(count: int, noun: str) -> str:
    """Signed delta with a correctly-numbered noun: '+1 question', '-3 questions', '0 questions'."""
    sign = f"{count:+d}" if count else "0"
    return f"{sign} {noun}{'' if abs(count) == 1 else 's'}"


def _count(count: int, noun: str) -> str:
    """Unsigned count with a correctly-numbered noun: '1 question', '3 questions'."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _no_overlap_note(q: "Question") -> str:
    named = ", ".join(f"`{t}`" for t in q.tokens)
    if named:
        return f"{q.id} names {named}, which `{q.expected_chunk_id}` never uses"
    return f"{q.id} names no identifier that `{q.expected_chunk_id}` shares"


def chunk_key(chunk: Chunk) -> str:
    return f"{chunk.source}#{chunk.chunk_id}"


@dataclass
class Question:
    id: str
    question: str
    expected_chunk_id: str
    article_id: str
    product_area: str
    exact_token: bool
    tokens: list[str]
    answer_contains: list[str]
    note: str
    # Filled in at load time: which of `tokens` the labelled chunk actually
    # contains. A question can name a rare identifier that appears nowhere in
    # its own answer chunk, in which case BM25 has no lexical signal to offer
    # and saying otherwise would be a story rather than a finding.
    shared_literals: list[str] = field(default_factory=list)


@dataclass
class Retrieved:
    """One arm's result for one question."""

    chunk_ids: list[str]
    scores: list[float]
    latency_ms: float
    rank: Optional[int]  # 1-based rank of the expected chunk over the whole corpus

    @property
    def hit3(self) -> bool:
        return self.rank is not None and self.rank <= TOP_K

    @property
    def hit1(self) -> bool:
        return self.rank == 1

    @property
    def rr(self) -> float:
        return 1.0 / self.rank if self.rank else 0.0

    def top(self, k: int = TOP_K) -> list[str]:
        return self.chunk_ids[:k]


@dataclass
class Arm:
    key: str
    label: str
    change: str
    run: Callable[[str, int], list[tuple[Chunk, float]]]
    results: dict[str, Retrieved] = field(default_factory=dict)

    def _rate(self, attr: str) -> float:
        return sum(getattr(r, attr) for r in self.results.values()) / len(self.results)

    @property
    def hits3(self) -> int:
        return sum(r.hit3 for r in self.results.values())

    @property
    def hits1(self) -> int:
        return sum(r.hit1 for r in self.results.values())

    @property
    def hit_rate3(self) -> float:
        return self._rate("hit3")

    @property
    def hit_rate1(self) -> float:
        return self._rate("hit1")

    @property
    def mrr(self) -> float:
        return self._rate("rr")

    @property
    def p50_ms(self) -> float:
        return statistics.median(r.latency_ms for r in self.results.values())


def load_questions() -> list[Question]:
    rows = []
    for line in GOLDEN_SET.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(Question(**json.loads(line)))
    return rows


def annotate_shared_literals(questions: list[Question], chunks_by_id: dict[str, Chunk]) -> None:
    """Record which declared tokens the question and its labelled chunk share verbatim."""
    for q in questions:
        body = _normalise(chunks_by_id[q.expected_chunk_id].text)
        asked = _normalise(q.question)
        q.shared_literals = [
            t for t in q.tokens if _normalise(t) in body and _normalise(t) in asked
        ]


def evaluate(arm: Arm, questions: list[Question], corpus_size: int) -> None:
    """
    Retrieve the whole ranked corpus once per query so the expected chunk's rank
    is always known - that is what distinguishes "ranked 4th" from "never
    surfaced" in the failure inspection. Latency is timed separately at the real
    top_k, because ranking 21 chunks is not what production does.
    """
    for q in questions:
        full = arm.run(q.question, corpus_size)
        ids = [chunk_key(c) for c, _ in full]
        rank = ids.index(q.expected_chunk_id) + 1 if q.expected_chunk_id in ids else None

        arm.run(q.question, TOP_K)  # warm-up, not timed
        samples = []
        for _ in range(LATENCY_REPEATS):
            start = time.perf_counter()
            arm.run(q.question, TOP_K)
            samples.append((time.perf_counter() - start) * 1000.0)

        arm.results[q.id] = Retrieved(
            chunk_ids=ids,
            scores=[round(float(s), 4) for _, s in full],
            latency_ms=statistics.median(samples),
            rank=rank,
        )


# --- generation check ---------------------------------------------------------


JUDGE_PROMPT = (
    "You are grading a support answer against a list of gold facts taken from the "
    "source document. Reply with exactly one word: YES if the answer states all the "
    "gold facts (wording, punctuation, currency symbols and number formatting may "
    "differ freely - '2500' and 'Rs 2,500' are the same fact), or NO if the answer "
    "contradicts a gold fact or leaves one out."
)


def check_generation(questions: list[Question], arm: Arm, chunks_by_id: dict[str, Chunk]):
    """
    Ask the real LLM with the baseline arm's top-3 context, then grade it.

    Returns {qid: (correct | None, answer_text, how_graded)}. None means the
    check could not run at all. See the module docstring for why the grading is
    a substring pre-pass backed by an LLM judge rather than a substring test on
    its own.
    """
    blank = {q.id: (None, "", "not measured") for q in questions}
    try:
        from openai import OpenAI

        from app.config import settings

        api_key = (settings.groq_api_key or "").strip()
        if not api_key:
            print("  GROQ_API_KEY unset - generation not measured")
            return blank
        client = OpenAI(api_key=api_key, base_url=settings.groq_base_url)
    except Exception as exc:  # pragma: no cover - credentials / import problem
        print(f"  generation check unavailable: {exc}")
        return blank

    def judge(question: str, facts: list[str], answer: str) -> Optional[bool]:
        try:
            reply = client.chat.completions.create(
                model=settings.groq_model,
                temperature=0,
                messages=[
                    {"role": "system", "content": JUDGE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Question: {question}\n"
                            f"Gold facts: {'; '.join(facts)}\n"
                            f"Answer: {answer}"
                        ),
                    },
                ],
            )
        except Exception as exc:  # pragma: no cover - network failure mid-run
            print(f"    judge call failed ({exc})")
            return None
        return "yes" in (reply.choices[0].message.content or "").strip().lower()[:6]

    out = {}
    for q in questions:
        r = arm.results[q.id]
        context = [(chunks_by_id[cid], score) for cid, score in zip(r.top(), r.scores[:TOP_K])]
        try:
            # temperature=0: the report is a deliverable, so the generation
            # column has to be the same on a re-run.
            answer = answer_with_groq(
                client, settings.groq_model, q.question, context, temperature=0.0
            )
        except Exception as exc:  # pragma: no cover - network failure mid-run
            print(f"  {q.id}: generation call failed ({exc})")
            out[q.id] = (None, "", "not measured")
            continue
        answer = " ".join(answer.split())
        flat = _normalise(answer)
        if all(_normalise(fact) in flat for fact in q.answer_contains):
            out[q.id] = (True, answer, "substring")
            print(f"  {q.id}: generation ok (substring)")
            continue
        verdict = judge(q.question, q.answer_contains, answer)
        how = "not measured" if verdict is None else "llm judge"
        out[q.id] = (verdict, answer, how)
        state = "not measured" if verdict is None else ("ok" if verdict else "WRONG")
        print(f"  {q.id}: generation {state} ({how})")
    return out


# The pre-LLM short-circuit string from answer_with_groq. Matching on it is how
# the harness tells "the model answered badly" from "the model was never asked".
GATE_REFUSAL = "I don't know. That isn't covered in the documents I have."


def classify(q: Question, base: Retrieved, generation) -> tuple[str, str]:
    """
    R    - correct chunk exists in the corpus but is not in the baseline top 3.
    G    - correct chunk was retrieved, but the LLM answered wrongly from it.
    Gate - correct chunk was retrieved, and SCORE_THRESHOLD refused the question
           before the LLM was ever called.
    Not-In-Corpus - the answer is not in any indexed chunk.

    `Gate` is a fourth class the assignment does not name, and it is kept
    separate rather than folded into one of the three because none of them is
    true of it: retrieval succeeded, generation never ran, and the answer is
    sitting in the corpus at the top of the ranking. Recording it as G would
    blame the model for a refusal it was never consulted about, and would send
    the fix at the prompt instead of at SCORE_THRESHOLD.

    Every gold label is verified to exist before the run, so Not-In-Corpus can
    only fire if the corpus changed underneath the golden set.
    """
    correct, answer, how = generation.get(q.id, (None, "", ""))
    if base.rank is None:
        return "Not-In-Corpus", (
            f"`{q.expected_chunk_id}` was not returned at any rank - the labelled chunk is "
            f"no longer in the index"
        )
    if not base.hit3:
        return "R", (
            f"expected `{q.expected_chunk_id}` sits at dense rank {base.rank}, outside the top 3 "
            f"(returned {', '.join(f'`{c}`' for c in base.top())})"
        )
    if answer.strip() == GATE_REFUSAL:
        return "Gate", (
            f"`{q.expected_chunk_id}` was retrieved at **rank {base.rank}** with cosine "
            f"{base.scores[0]:.4f}, below `SCORE_THRESHOLD` - the app refused before calling the "
            f"LLM. Retrieval did its job; the threshold rejected the answer it had already found"
        )
    if correct is False:
        quoted = answer if len(answer) <= 300 else answer[:300].rstrip() + "..."
        return "G", (
            f"expected `{q.expected_chunk_id}` was retrieved at rank {base.rank}, so retrieval "
            f"succeeded; the answer was still graded wrong against "
            f"{', '.join(repr(f) for f in q.answer_contains)} by the {how}. Answer: \"{quoted}\""
        )
    return "", ""


# --- report -------------------------------------------------------------------


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_report(
    questions: list[Question],
    arms: dict[str, Arm],
    combined: Arm,
    generation,
    chosen: Arm,
    failures: dict[str, tuple[str, str]],
    chunk_count: int,
) -> str:
    base = arms["baseline"]
    n = len(questions)
    lines: list[str] = []
    w = lines.append

    # --- 9 ---------------------------------------------------------------
    w("## 9. Week 4 golden set")
    w("")
    w(
        f"`backend/eval/golden_set.jsonl` - {n} realistic support questions written against the 6 "
        f"indexed articles, each labelled with the single `chunk_id` that answers it. "
        f"{sum(q.exact_token for q in questions)} carry an exact identifier (plan name, error code, "
        f"or charge amount). Labels were assigned by reading the chunked corpus **before any "
        f"retrieval was run**, and the harness re-verifies at startup that every labelled chunk "
        f"still contains its gold facts."
    )
    w("")
    w(
        f"Questions are phrased the way a support ticket is written rather than the way the article "
        f"is worded - 'the light on the box is red', not 'solid red status LED on the ONT' - because "
        f"a retriever that only works on the document's own vocabulary is not being tested."
    )
    w("")
    w(
        f"Chunk ids are stable for the shipped configuration `{STRATEGY}/{CHUNK_SIZE}/{OVERLAP}` "
        f"({chunk_count} chunks). Changing chunking invalidates the labels."
    )
    w("")
    w("| ID | Question | Expected chunk_id | Exact token | Why this chunk |")
    w("| --- | --- | --- | --- | --- |")
    for q in questions:
        w(
            f"| {q.id} | {q.question} | `{q.expected_chunk_id}` | "
            f"{'yes' if q.exact_token else 'no'} | {q.note} |"
        )
    w("")

    # --- 10 --------------------------------------------------------------
    w("## 10. Baseline hit-rate@3 (Week 3 retriever, unchanged)")
    w("")
    w(
        f"Dense cosine over FAISS, top 3, no filter - `VectorStore.search`, the exact code that "
        f"produced sections 1-8."
    )
    w("")
    w(f"**Baseline hit-rate@3 = {base.hits3}/{n} = {pct(base.hit_rate3)}.** "
      f"p50 retrieval latency = {base.p50_ms:.1f} ms.")
    w("")
    if base.hit_rate3 >= 1.0:
        w(
            f"That number is at the ceiling, and the ceiling is the finding: the index holds "
            f"{chunk_count} chunks, so a top-3 window is {TOP_K / chunk_count:.0%} of the entire "
            f"corpus. **Hit-rate@3 cannot separate two retrievers here** - it is saturated before "
            f"the experiment starts. This is the same problem section 7 records for Article Hit@k, "
            f"and the same fix applies: report a metric that still moves."
        )
    else:
        w(
            f"Hit-rate@3 does move on this corpus, which it did not before KB-007 "
            f"(`airfiber_legacy_plans.md`) was added. That article introduces six further plan "
            f"packs whose descriptions differ from the retail ones mainly in a numeric identifier, "
            f"and it is what turns a top-3 window - {TOP_K} of {chunk_count} chunks, "
            f"{TOP_K / chunk_count:.0%} of the corpus - into a real constraint rather than a "
            f"formality. Even so, one miss out of {n} is a coarse signal: a single question is 8.3 "
            f"percentage points, so @3 alone cannot rank two retrievers with any confidence."
        )
    w("")
    w(
        f"Hit@1 = {base.hits1}/{n} = {pct(base.hit_rate1)}, MRR = {base.mrr:.3f}. Every comparison "
        f"below reports all three, and section 14 decides on the ones that discriminate."
    )
    w("")
    w("| ID | Rank of expected chunk | Hit@3 | Hit@1 | Top-3 returned |")
    w("| --- | --- | --- | --- | --- |")
    for q in questions:
        r = base.results[q.id]
        w(
            f"| {q.id} | {r.rank if r.rank else 'not ranked'} | "
            f"{'HIT' if r.hit3 else '**MISS**'} | {'HIT' if r.hit1 else 'miss'} | "
            f"{', '.join(f'`{c}`' for c in r.top())} |"
        )
    w("")

    # --- 11 --------------------------------------------------------------
    w("## 11. Failure inspection and classification")
    w("")
    w(
        "R = retrieval failure (the correct chunk exists but the top 3 did not return it). "
        "G = generation failure (the correct chunk was retrieved, the LLM still answered wrongly). "
        "Not-In-Corpus = the answer is in no indexed chunk. **Gate** is a fourth class the "
        "assignment does not name, added because one question fits none of the three: retrieval "
        "succeeded, generation never ran, and `SCORE_THRESHOLD` refused a question the corpus "
        "answers. Filing that as G would blame the model for a call it was never asked to make."
    )
    w("")
    tally = {"R": 0, "G": 0, "Gate": 0, "Not-In-Corpus": 0}
    for q in questions:
        kind = failures[q.id][0]
        if kind:
            tally[kind] += 1
    misses = [q for q in questions if failures[q.id][0]]

    if misses:
        w("| ID | Question | Class | Evidence |")
        w("| --- | --- | --- | --- |")
        for q in misses:
            kind, evidence = failures[q.id]
            w(f"| {q.id} | {q.question} | **{kind}** | {evidence} |")
    else:
        w(
            f"**There are no failures to classify at k=3.** The baseline retrieved the labelled "
            f"chunk for all {n} questions, and every generated answer stated its gold facts. R = 0 "
            f"is a real result, not a missing measurement - it is what a {chunk_count}-chunk corpus "
            f"with a 3-slot window produces."
        )
        w("")
        w(
            "G = 0 is a measured result too, and it took two passes to establish. A plain substring "
            "test over the model's prose flagged 7 of 12 answers as generation failures; reading "
            "them showed all 7 were correct and the test was tripping over formatting - `Rs 2,500` "
            "against the gold `2500`, a Unicode hyphen in `5-day`, `the MAC address isn't "
            "whitelisted` against `MAC address not whitelisted`. Those 7 are now graded by an LLM "
            "judge shown the question, the gold facts and the answer. Had the first number been "
            "reported, the failure tally would have read G = 7 and this report would have argued "
            "for a prompt change that nothing in the evidence supports."
        )
    w("")
    gate_cases = [q for q in questions if failures[q.id][0] == "Gate"]
    if gate_cases:
        w("")
        for q in gate_cases:
            base_r = base.results[q.id]
            w(
                f"**{q.id} is "
                f"{'the one real defect this golden set found' if tally['R'] == 0 else 'a second defect, unrelated to the ' + _count(tally['R'], 'retrieval failure') + ' above'}, "
                f"and it is not a retrieval defect.** The labelled chunk was retrieved at rank "
                f"{base_r.rank}, but its cosine "
                f"of {base_r.scores[0]:.4f} falls under `SCORE_THRESHOLD` (0.15), so "
                f"`answer_with_groq` short-circuits and the user is told the documents do not cover "
                f"a question the documents answer in full. Neither Week 4 improvement can touch "
                f"this: BM25 and the cross-encoder change the *order* of results, and the gate reads "
                f"the dense cosine of whatever comes back."
            )
            w("")
            w(
                f"It is the failure mode section 5 predicted. `{q.question}` is phrased the way a "
                f"customer types it, and the threshold was tuned against questions phrased the way "
                f"the documents are written - section 7 already records that the answerable and "
                f"out-of-scope score populations overlap and that no separating value exists. This "
                f"is that overlap arriving in practice: 0.310 for an out-of-scope Netflix question "
                f"against {base_r.scores[0]:.4f} for an answerable one. Fixing it means changing the "
                f"refusal design, not the retriever - and that is a second change, so it is recorded "
                f"here and deliberately not made."
            )
    w("")
    w("### Failure tally")
    w("")
    w("| Class | Count | Evidence source |")
    w("| --- | --- | --- |")
    w(f"| R (retrieval) | {tally['R']} | rank of the labelled chunk in the full dense ranking |")
    generation_measured = any(v[0] is not None for v in generation.values())
    graded = [v[2] for v in generation.values()]
    how = (
        f"live Groq call per question; {graded.count('substring')} graded by exact gold-fact match, "
        f"{graded.count('llm judge')} escalated to an LLM judge"
        if generation_measured
        else "**not measured** - no Groq key on this run"
    )
    w(f"| G (generation) | {tally['G']} | {how} |")
    w(
        f"| Gate (refusal threshold) | {tally['Gate']} | answer equals the pre-LLM refusal string "
        f"while the labelled chunk is already in the top 3 |"
    )
    w(f"| Not-In-Corpus | {tally['Not-In-Corpus']} | gold labels re-verified against the index at startup |")
    w(f"| Passed | {n - sum(tally.values())} | - |")
    w("")

    # rank-1 diagnostic, which is where the failures actually live
    rank1_failures = [q for q in questions if not base.results[q.id].hit1]
    if rank1_failures:
        w("### Rank-1 failures (the diagnostic that k=3 hides)")
        w("")
        w(
            f"Hit-rate@3 surfaced {_count(tally['R'], 'retrieval failure')}, too few to choose "
            f"between two retrievers on. The same inspection is therefore repeated at rank 1, which "
            f"is stricter and where the baseline misses {_count(len(rank1_failures), 'question')}. "
            f"These are cases where the correct chunk was retrieved but out-ranked - exactly the "
            f"symptom both Week 4 improvements target - so this is the evidence section 12 chooses "
            f"on."
        )
        w("")
        w("| ID | Question | Expected rank | Out-ranked by | Exact/rare token in the question |")
        w("| --- | --- | --- | --- | --- |")
        for q in rank1_failures:
            r = base.results[q.id]
            tokens = ", ".join(f"`{t}`" for t in q.tokens) if q.tokens else "-"
            w(
                f"| {q.id} | {q.question} | {r.rank} | `{r.chunk_ids[0]}` "
                f"(cosine {r.scores[0]:.3f} vs {r.scores[r.rank - 1]:.3f}) | {tokens} |"
            )
        w("")
        exact_share = sum(1 for q in rank1_failures if q.exact_token)
        w(
            f"{exact_share} of {_count(len(rank1_failures), 'rank-1 failure')} "
            f"{'carries' if exact_share == 1 else 'carry'} an exact identifier that the embedding "
            f"model smears into a generic neighbourhood. In every "
            f"case the labelled chunk is already in the candidate pool - ranked too low, never "
            f"absent."
        )
        w("")

    # --- 12 --------------------------------------------------------------
    w("## 12. The one retrieval change")
    w("")
    if rank1_failures:
        ids = ", ".join(q.id for q in rank1_failures)
        lexical = [q for q in rank1_failures if q.shared_literals]
        w(
            f"The failure evidence narrows the choice but does not settle it, and it is worth being "
            f"exact about that. Both candidates address a different symptom: BM25 + RRF recovers a "
            f"chunk the dense retriever never surfaced, while a cross-encoder re-orders a shortlist "
            f"that already holds it. Every failure measured above ({ids}) is the second kind - the "
            f"labelled chunk sat at rank "
            f"{', '.join(sorted({str(base.results[q.id].rank) for q in rank1_failures}))} of the "
            f"full ranking, never absent - which on its face argues for the reranker."
        )
        w("")
        if lexical:
            evidence = "; ".join(
                f"{q.id} shares {', '.join(f'`{t}`' for t in q.shared_literals)} verbatim with "
                f"`{q.expected_chunk_id}`"
                for q in lexical
            )
            w(
                f"**BM25 + RRF is chosen, on this evidence:** {evidence}. A literal that rare carries "
                f"high IDF for BM25 and is exactly what a 384-dimension MiniLM embedding averages "
                f"away, so the lexical retriever has a signal here that the dense one structurally "
                f"cannot recover."
            )
        else:
            w(
                "**BM25 + RRF is chosen**, though the evidence for it is weaker than the corpus "
                "suggested it would be."
            )
        non_lexical = [q for q in rank1_failures if not q.shared_literals]
        if non_lexical:
            w("")
            w(
                f"The case is not clean, and overstating it would be the easy mistake here. "
                f"{', '.join(q.id for q in non_lexical)} "
                f"{'is' if len(non_lexical) == 1 else 'are'} **not** a rare-literal failure: the "
                f"question's distinctive wording appears nowhere in the labelled chunk "
                f"({'; '.join(_no_overlap_note(q) for q in non_lexical)}). "
                f"Whatever BM25 does for {'that question' if len(non_lexical) == 1 else 'those questions'}, "
                f"it will not be the mechanism claimed "
                f"above - which is one more reason to measure both arms rather than reason about "
                f"them."
            )
        w("")
        w(
            "Cross-encoder reranking is measured on the same 12 questions so the choice is made "
            "against a real alternative rather than asserted."
        )
        w("")
    else:
        w(
            "With no measured failures there is no evidence to select between the two candidate "
            "improvements. BM25 + RRF is taken as the change on the prior that this corpus is full "
            "of exact identifiers, and measured below."
        )
        w("")
    w(
        "Each arm differs from the baseline by exactly one retrieval variable. Embedding model "
        "(`all-MiniLM-L6-v2`), chunking (`heading/1000/100`), prompt, LLM and top_k are identical in "
        "every row."
    )
    w("")
    w("| Arm | Retrieval | Change vs baseline | Hit@3 | Hit@1 | MRR | p50 latency |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for arm in (arms["baseline"], arms["bm25"], arms["rerank"], combined):
        w(
            f"| {arm.label} | {arm.key} | {arm.change} | "
            f"{pct(arm.hit_rate3)} | {pct(arm.hit_rate1)} | {arm.mrr:.3f} | {arm.p50_ms:.1f} ms |"
        )
    w("")
    w(
        f"The stacked row is the mode the app currently ships as `week4`. It combines two changes, "
        f"so it is **not eligible** as the single improvement - it is listed only to show what the "
        f"full stack does."
    )
    w("")

    # --- 13 --------------------------------------------------------------
    w("## 13. Before -> after on the same 12 questions")
    w("")
    w(f"Baseline (A) versus the chosen single change ({chosen.label}), same golden set, same labels.")
    w("")
    w(f"- **Hit-rate@3: {pct(base.hit_rate3)} -> {pct(chosen.hit_rate3)}** "
      f"({_plural(chosen.hits3 - base.hits3, 'question')})")
    w(f"- **Hit-rate@1: {pct(base.hit_rate1)} -> {pct(chosen.hit_rate1)}** "
      f"({_plural(chosen.hits1 - base.hits1, 'question')})")
    w(f"- **MRR: {base.mrr:.3f} -> {chosen.mrr:.3f}** ({chosen.mrr - base.mrr:+.3f})")
    w(f"- **p50 retrieval latency: {base.p50_ms:.1f} ms -> {chosen.p50_ms:.1f} ms** "
      f"({chosen.p50_ms - base.p50_ms:+.1f} ms)")
    w("")
    w(
        f"Both p50 figures are dominated by the MiniLM query encode, which both arms pay. The BM25 "
        f"scoring pass over {chunk_count} chunks is not measurable against it, which is why the "
        f"two medians can land either side of each other from run to run."
    )
    w("")
    w("Per-question outcome. `fixed` / `not fixed` grade the baseline's failures; `regressed` marks a question the change broke.")
    w("")
    w("| ID | Baseline rank | After rank | Baseline class | Hit@3 outcome | Rank-1 outcome |")
    w("| --- | --- | --- | --- | --- | --- |")
    fixed3 = unfixed3 = regressed3 = 0
    fixed1 = regressed1 = 0
    for q in questions:
        before, after = base.results[q.id], chosen.results[q.id]
        kind = failures[q.id][0]
        if not before.hit3 and after.hit3:
            out3, fixed3 = "**fixed**", fixed3 + 1
        elif not before.hit3 and not after.hit3:
            out3, unfixed3 = "not fixed", unfixed3 + 1
        elif before.hit3 and not after.hit3:
            out3, regressed3 = "**regressed**", regressed3 + 1
        else:
            out3 = "unchanged (hit)"
        if not before.hit1 and after.hit1:
            out1, fixed1 = "**fixed**", fixed1 + 1
        elif before.hit1 and not after.hit1:
            out1, regressed1 = "**regressed**", regressed1 + 1
        elif before.hit1:
            out1 = "unchanged (hit)"
        else:
            out1 = "not fixed"
        w(
            f"| {q.id} | {before.rank} | {after.rank} | {kind or '-'} | {out3} | {out1} |"
        )
    w("")
    w(
        f"**Hit@3:** of the {_count(tally['R'], 'baseline R failure')}, {fixed3} fixed and "
        f"{unfixed3} not fixed; {_count(regressed3, 'regression')}. "
        f"**Rank 1:** {fixed1} fixed, {regressed1} regressed. "
        f"G failures: {tally['G']} - a retrieval change cannot fix a generation error, and none is "
        f"expected to. Not-In-Corpus: {tally['Not-In-Corpus']} - unfixable by any retriever."
    )
    w("")
    if fixed1:
        fixed_ids = [
            q.id for q in questions
            if not base.results[q.id].hit1 and chosen.results[q.id].hit1
        ]
        regressed_ids = [
            q.id for q in questions
            if base.results[q.id].hit1 and not chosen.results[q.id].hit1
        ]
        lexical_ids = {q.id for q in rank1_failures if q.shared_literals}
        lexical_fixed = [i for i in fixed_ids if i in lexical_ids]
        w(
            f"BM25 promoted {_count(len(fixed_ids), 'rank-1 failure')} "
            f"({', '.join(fixed_ids)}) to rank 1. But only {len(lexical_fixed)} of them"
            f"{' (' + ', '.join(lexical_fixed) + ')' if lexical_fixed else ''} "
            f"{'is' if len(lexical_fixed) == 1 else 'are'} the rare-literal case the change was "
            f"chosen for - the rest were carried by ordinary lexical overlap. "
            f"The mechanism argued for the change explains less of its benefit than it appeared to."
        )
        w("")
        net1 = fixed1 - regressed1
        w(
            f"Against that it cost {_count(len(regressed_ids), 'question')}"
            f"{' (' + ', '.join(regressed_ids) + ')' if regressed_ids else ''}, each a case where "
            f"the question shares common vocabulary with a chunk that does not answer it. BM25 has "
            f"no way to tell a merely topical word from a decisive one, so wherever the dense "
            f"retriever was already correct the lexical signal is pure noise."
        )
        w("")
        w(
            f"Net at rank 1: **{_plural(net1, 'question')}** out of {n}. "
            + (
                f"That is a positive result and it is also a thin one - a single question is "
                f"{1 / n * 100:.1f} percentage points, so a set of {n} cannot distinguish a real "
                f"{abs(net1)}-question effect from sampling noise. Section 14 takes it as directional "
                f"evidence, not as a measured effect size."
                if net1 > 0
                else (
                    f"The change is net negative and there is no reading of these numbers that "
                    f"supports it as a default."
                    if net1 < 0
                    else f"The change moves questions in both directions and nets to zero, which is "
                    f"the least actionable outcome available: it costs a dependency and a second "
                    f"ranking stage to buy nothing measurable."
                )
            )
        )
        w("")

    # --- 14 --------------------------------------------------------------
    w("## 14. Shipping decision")
    w("")
    improves = (
        chosen.hit_rate3 > base.hit_rate3
        or (chosen.hit_rate3 == base.hit_rate3 and chosen.hit_rate1 > base.hit_rate1)
    )
    w("**Decision: " + ("ship as the default retriever.**" if improves else "do not ship as the default. Keep it behind the `week4` toggle.**"))
    w("")
    w("| Metric | Before | After | Delta |")
    w("| --- | --- | --- | --- |")
    w(f"| Hit-rate@3 | {pct(base.hit_rate3)} | {pct(chosen.hit_rate3)} | {(chosen.hit_rate3 - base.hit_rate3) * 100:+.1f} pp |")
    w(f"| Hit-rate@1 | {pct(base.hit_rate1)} | {pct(chosen.hit_rate1)} | {(chosen.hit_rate1 - base.hit_rate1) * 100:+.1f} pp |")
    w(f"| MRR | {base.mrr:.3f} | {chosen.mrr:.3f} | {chosen.mrr - base.mrr:+.3f} |")
    w(f"| p50 retrieval latency | {base.p50_ms:.1f} ms | {chosen.p50_ms:.1f} ms | {chosen.p50_ms - base.p50_ms:+.1f} ms |")
    w(f"| Regressions (rank 1) | - | - | {regressed1} |")
    w("")
    if improves:
        w(
            f"Ship, on a narrow but consistent margin. At rank 1 the change fixes "
            f"{_count(fixed1, 'question')} and breaks {_count(regressed1, 'question')}, a net "
            f"{_plural(fixed1 - regressed1, 'question')}; MRR moves "
            f"{chosen.mrr - base.mrr:+.3f}. Latency is not a factor at "
            f"{chosen.p50_ms - base.p50_ms:+.1f} ms - both arms are dominated by the query encode, "
            f"and both are noise against a Groq completion measured in hundreds of milliseconds."
        )
        w("")
        w("Two things this decision is **not**:")
        w("")
        w(
            f"- **It is not a strong result.** One question is {1 / n * 100:.1f} percentage points "
            f"on a {n}-question set. A net gain of {fixed1 - regressed1} is directional evidence, "
            f"not a measured effect size, and it would not survive a significance test. The honest "
            f"summary is that BM25 + RRF is *not worse* and is *probably* better on a corpus with "
            f"near-duplicate identifiers."
        )
        if regressed3:
            w(
                f"- **It is not free at k=3.** Hit-rate@3 is unchanged at {pct(chosen.hit_rate3)} "
                f"because the change fixed {_count(fixed3, 'question')} and broke "
                f"{_count(regressed3, 'question')}. Trading one failure for another is not the same "
                f"as removing one, and the questions are not interchangeable - check the table above "
                f"before treating a flat headline as no change."
            )
        w("")
        w(
            f"What changed since the previous run of this harness is the corpus, not the code. "
            f"Before KB-007 the same comparison came out net negative (Hit@1 83.3% -> 75.0%) and "
            f"this section said do-not-ship. Adding an article full of near-duplicate plan "
            f"identifiers is exactly the condition the old verdict named as missing, and the sign "
            f"of the result flipped when it arrived. That is the finding worth carrying forward: "
            f"**the retriever was never the variable - the corpus was.**"
        )
    else:
        w(
            f"The numbers do not support making it the default. Hit-rate@3 is unchanged at "
            f"{pct(chosen.hit_rate3)} because the baseline was already saturated, and on the metric "
            f"that still discriminates the change is net negative: Hit@1 "
            f"{pct(base.hit_rate1)} -> {pct(chosen.hit_rate1)}, MRR {base.mrr:.3f} -> "
            f"{chosen.mrr:.3f}. Latency is not the reason - at "
            f"{chosen.p50_ms - base.p50_ms:+.1f} ms it would have been affordable if the accuracy "
            f"had moved the right way."
        )
        w("")
        w("What that does and does not mean:")
        w("")
        w(
            f"- **It is a verdict about this corpus, not about BM25.** Six articles and "
            f"{chunk_count} chunks is far too few for a lexical signal to pay for itself: with a "
            f"corpus this small the dense retriever has almost nothing to confuse the right chunk "
            f"with, while BM25 has enough common vocabulary to promote a wrong one. The mechanism "
            f"that makes hybrid retrieval win at scale - many near-duplicate candidates, where a "
            f"rare literal is the only disambiguator - does not exist here yet."
        )
        w(
            f"- **The stage still works and is still reachable.** `week4` mode stays in the app "
            f"behind the mode toggle, `/api/health` still reports which stages are live, and the "
            f"per-stage scores are still shown per citation. The default simply stays `week3`."
        )
        if tally["Gate"]:
            w(
                f"- **The change that this golden set actually justifies is not a retrieval change "
                f"at all.** {_count(tally['Gate'], 'question')} was refused by `SCORE_THRESHOLD` "
                f"despite its answer sitting at rank 1. That is the only user-visible defect found, "
                f"no reranker can fix it, and it is left unmade here precisely because the "
                f"assignment allows exactly one change and that budget was spent on retrieval. It "
                f"is the first thing to pick up next."
            )
        w(
            f"- **The re-test condition is explicit.** Re-run this harness when the corpus grows "
            f"past roughly a hundred chunks or when the golden set contains questions the baseline "
            f"actually fails at k=3. Until Hit@3 stops reading 100% for the baseline, this "
            f"experiment cannot measure the thing it is meant to measure."
        )
        w(
            f"- **Shipping it anyway would have been the mistake the Week 3 report already "
            f"documents.** Section 7 records that a saturated metric on a six-article corpus cannot "
            f"tell two configurations apart. Reading 100% -> 100% as 'no harm, ship it' repeats "
            f"exactly that error with a real cost attached."
        )
    w("")

    w("### Code diff - the one retrieval change")
    w("")
    w(
        "The change is confined to retrieval. Chunking, embedding, prompt and LLM call are byte-for-"
        "byte identical between the two runs; `RagService.retrieve` selects between them per request."
    )
    w("")
    w("```diff")
    w("  # backend/app/services/rag_service.py - RagService.retrieve")
    w("      k = top_k or self.top_k")
    w("+     if mode == WEEK4:")
    w("+         return self.store.search_hybrid(question, top_k=k, filters=filters)")
    w("      return [")
    w("          (chunk, Scored(index=-1, dense_score=score, dense_rank=rank))")
    w("          for rank, (chunk, score) in enumerate(")
    w("              self.store.search(question, top_k=k, filters=filters), start=1")
    w("          )")
    w("      ]")
    w("")
    w("  # backend/app/services/rag_service.py - VectorStore.search_hybrid (new method)")
    w("+ # BM25 and dense each rank the whole corpus; RRF fuses them by rank, not score.")
    w("+ keyword_hits = self.bm25.search(query, len(self.chunks)) if (use_keyword and self.bm25) else []")
    w("+ fused = reciprocal_rank_fusion({\"dense\": dense_order[:pool], \"keyword\": keyword_order[:pool]})")
    w("+ candidates = sorted(fused, key=lambda i: (fused[i], dense_scores.get(i, 0.0)), reverse=True)[:pool]")
    w("```")
    w("")
    w(
        "`VectorStore.search` - the Week 3 path behind every number in sections 1-8 - is not "
        "touched, so the baseline in this report is the same code that produced the Week 3 report. "
        "`search_hybrid`'s `use_keyword` and `rerank` flags exist so each stage can be switched on "
        "alone; that is what makes the one-variable arms above possible."
    )
    w("")
    w("### Reproduce")
    w("")
    w("```bash")
    w("cd backend && python scripts/evaluate_week4.py    # rewrites sections 9-14 of ../results.md")
    w("```")
    return "\n".join(lines)


def write_results(section: str) -> None:
    body = RESULTS.read_text(encoding="utf-8") if RESULTS.exists() else ""
    block = f"{MARK_START}\n\n{section}\n\n{MARK_END}\n"
    if MARK_START in body and MARK_END in body:
        head, rest = body.split(MARK_START, 1)
        _, tail = rest.split(MARK_END, 1)
        body = head + block + tail
    else:
        body = body.rstrip() + "\n\n" + block
    RESULTS.write_text(body, encoding="utf-8")


def main() -> None:
    questions = load_questions()
    print(f"Golden set: {len(questions)} questions from {GOLDEN_SET}")

    chunks = build_chunks(str(CORPUS), chunk_size=CHUNK_SIZE, overlap=OVERLAP, strategy=STRATEGY)
    chunks_by_id = {chunk_key(c): c for c in chunks}
    missing = [q.id for q in questions if q.expected_chunk_id not in chunks_by_id]
    if missing:
        raise SystemExit(f"Gold labels reference chunks that do not exist: {missing}")
    for q in questions:
        text = chunks_by_id[q.expected_chunk_id].text.lower()
        absent = [f for f in q.answer_contains if f.lower() not in text]
        if absent:
            raise SystemExit(f"{q.id}: labelled chunk does not contain {absent}")
    print(f"Indexed {len(chunks)} chunks at {STRATEGY}/{CHUNK_SIZE}/{OVERLAP}; all gold labels verified.")
    annotate_shared_literals(questions, chunks_by_id)

    store = VectorStore()
    store.index(chunks)

    if not BM25_AVAILABLE:
        raise SystemExit("rank_bm25 is not installed; the BM25 arm cannot be measured.")
    print(f"Loading reranker {RERANK_MODEL_NAME} ...")
    reranker = get_reranker()
    reranker.score("warm up", ["warm up"])
    if reranker.unavailable:
        raise SystemExit("Cross-encoder could not be loaded; the rerank arm cannot be measured.")

    def pairs(rows):
        return [(chunk, scored.dense_score) for chunk, scored in rows]

    arms = {
        "baseline": Arm(
            key="dense",
            label="A. Baseline (Week 3)",
            change="none - dense cosine over FAISS",
            run=lambda q, k: store.search(q, top_k=k),
        ),
        "bm25": Arm(
            key="dense + BM25/RRF",
            label="B. BM25 + RRF",
            change="**one change:** adds a lexical retriever, fused by reciprocal rank fusion",
            run=lambda q, k: pairs(
                store.search_hybrid(q, top_k=k, candidate_k=len(store.chunks), rerank=False, use_keyword=True)
            ),
        ),
        "rerank": Arm(
            key="dense + cross-encoder",
            label="C. Cross-encoder rerank",
            change="**one change:** rescores the dense candidate pool with a cross-encoder",
            run=lambda q, k: pairs(
                store.search_hybrid(q, top_k=k, candidate_k=len(store.chunks), rerank=True, use_keyword=False)
            ),
        ),
    }
    combined = Arm(
        key="dense + BM25/RRF + cross-encoder",
        label="A+B+C. Stacked (current `week4` mode)",
        change="_two_ changes - not eligible as the single improvement",
        run=lambda q, k: pairs(
            store.search_hybrid(q, top_k=k, candidate_k=len(store.chunks), rerank=True, use_keyword=True)
        ),
    )

    for name, arm in list(arms.items()) + [("combined", combined)]:
        print(f"Running arm {name} ...")
        evaluate(arm, questions, len(chunks))
        print(
            f"  hit@3 {arm.hits3}/{len(questions)}  hit@1 {arm.hits1}/{len(questions)}  "
            f"MRR {arm.mrr:.3f}  p50 {arm.p50_ms:.1f} ms"
        )

    print("Checking generation on the baseline arm ...")
    generation = check_generation(questions, arms["baseline"], chunks_by_id)
    failures = {q.id: classify(q, arms["baseline"].results[q.id], generation) for q in questions}

    # BM25 + RRF is the chosen single change; the failure analysis in section 11
    # is what selects it (every rank-1 failure carries a rare literal token).
    # It is compared against the baseline whether or not it wins - reporting a
    # change that did not pay off is the point of the exercise.
    chosen = arms["bm25"]

    report = build_report(questions, arms, combined, generation, chosen, failures, len(chunks))
    write_results(report)
    print(f"\nWrote Week 4 sections to {RESULTS}")
    print(
        f"Hit@3 {pct(arms['baseline'].hit_rate3)} -> {pct(chosen.hit_rate3)} | "
        f"Hit@1 {pct(arms['baseline'].hit_rate1)} -> {pct(chosen.hit_rate1)} | "
        f"p50 {arms['baseline'].p50_ms:.1f} -> {chosen.p50_ms:.1f} ms"
    )


if __name__ == "__main__":
    main()
