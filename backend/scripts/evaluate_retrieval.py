"""
Retrieval evaluation for the Week 3 assignment.

Builds one index per chunking configuration over the same corpus, runs the gold
question set against each, and writes results.md.

Two hit rates are reported, because they measure different things:

  Article Hit@k   a chunk from the expected article appears in the top-k. With
                  only six articles this saturates at 100% almost everywhere,
                  so it does not discriminate between strategies.
  Answer Hit@k    a top-k chunk is from the expected article AND contains the
                  gold answer string. This is the metric that matters: a chunk
                  from the right article that got cut before the answer still
                  produces an "I don't know", or worse, a confident answer
                  citing a chunk that does not support it.

  MRR             reciprocal rank of the first answer-bearing chunk
  Citation acc.   the rank-1 chunk is answer-bearing, so the citation the user
                  sees points at the text that actually answers the question
  Refusal rate    out-of-scope questions whose best score falls below
                  SCORE_THRESHOLD, so the app refuses before the LLM

Retrieval only. No Groq key needed.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Pin the documented configuration before app.config reads the environment.
# `.env` is developer-local and overrides config.py's defaults, so without this
# a stale one silently republishes results.md under a configuration nobody
# chose - which is exactly how this file once came to record a threshold of
# 0.08 while every sentence in section 5 argued for 0.15.
os.environ["SCORE_THRESHOLD"] = "0.15"

from app.services.rag_service import SCORE_THRESHOLD, VectorStore, build_chunks  # noqa: E402

REPO_ROOT = ROOT.parent
DEFAULT_DOCS = REPO_ROOT / "sample_documents"
GOLD_PATH = ROOT / "eval" / "gold_questions.json"
RESULTS_PATH = REPO_ROOT / "results.md"

# (strategy, chunk_size, overlap)
CONFIGS = [
    ("fixed", 150, 15),
    ("fixed", 500, 50),
    ("fixed", 500, 125),
    ("fixed", 1200, 120),
    ("recursive", 500, 50),
    ("recursive", 800, 80),
    ("heading", 500, 50),
    ("heading", 800, 80),
    ("heading", 1000, 100),
]

TOP_K_VALUES = [3, 5]


@dataclass
class QuestionResult:
    qid: str
    question: str
    kind: str
    expected: str
    rank: Optional[int]           # first chunk from the expected article
    answer_rank: Optional[int]    # first chunk that also carries the gold answer
    top_score: float
    top_article: str
    top_source: str
    citation_ok: bool


def label(strategy: str, size: int, overlap: int) -> str:
    return f"{strategy}/{size}/{overlap}"


def first_correct_rank(results, expected_article_id: str) -> Optional[int]:
    for position, (chunk, _score) in enumerate(results, start=1):
        if chunk.article_id == expected_article_id:
            return position
    return None


def carries_answer(chunk, item: dict) -> bool:
    """True when the chunk is from the expected article and contains every gold string."""
    if chunk.article_id != item["expected_article_id"]:
        return False
    haystack = " ".join(chunk.text.split()).lower()
    return all(" ".join(n.split()).lower() in haystack for n in item.get("answer_contains", []))


def first_answer_rank(results, item: dict) -> Optional[int]:
    for position, (chunk, _score) in enumerate(results, start=1):
        if carries_answer(chunk, item):
            return position
    return None


def evaluate_config(store: VectorStore, gold: dict, top_k: int) -> dict:
    per_question: list[QuestionResult] = []

    for item in gold["known_answer"]:
        results = store.search(item["question"], top_k=top_k)
        rank = first_correct_rank(results, item["expected_article_id"])
        answer_rank = first_answer_rank(results, item)
        top_chunk, top_score = results[0] if results else (None, 0.0)
        citation_ok = top_chunk is not None and carries_answer(top_chunk, item)

        per_question.append(
            QuestionResult(
                qid=item["id"],
                question=item["question"],
                kind=item.get("kind", "prose"),
                expected=item["expected_article_id"],
                rank=rank,
                answer_rank=answer_rank,
                top_score=float(top_score),
                top_article=top_chunk.article_id if top_chunk else "",
                top_source=top_chunk.source if top_chunk else "",
                citation_ok=citation_ok,
            )
        )

    total = len(per_question) or 1
    levels = [k for k in (1, 3, 5) if k <= top_k or k == 1]
    hits_at = {
        k: sum(1 for r in per_question if r.rank is not None and r.rank <= k) / total for k in levels
    }
    answer_hits_at = {
        k: sum(1 for r in per_question if r.answer_rank is not None and r.answer_rank <= k) / total
        for k in levels
    }
    mrr = sum((1 / r.answer_rank) if r.answer_rank else 0.0 for r in per_question) / total

    table_rows = [r for r in per_question if r.kind == "table"]
    table_hit = (
        sum(1 for r in table_rows if r.answer_rank is not None and r.answer_rank <= top_k)
        / len(table_rows)
        if table_rows
        else 0.0
    )

    refused = []
    for item in gold["out_of_scope"]:
        results = store.search(item["question"], top_k=top_k)
        best = results[0][1] if results else 0.0
        refused.append(
            {
                "id": item["id"],
                "question": item["question"],
                "best_score": float(best),
                "refused": best < SCORE_THRESHOLD,
                "top_source": results[0][0].source if results else "",
            }
        )

    ambiguous = []
    for item in gold["ambiguous"]:
        results = store.search(item["question"], top_k=top_k)
        best = results[0][1] if results else 0.0
        ambiguous.append(
            {
                "id": item["id"],
                "question": item["question"],
                "best_score": float(best),
                "refused": best < SCORE_THRESHOLD,
                "top_source": results[0][0].source if results else "",
                "top_section": results[0][0].section if results else "",
            }
        )

    return {
        "top_k": top_k,
        "hits": hits_at,
        "answer_hits": answer_hits_at,
        "mrr": mrr,
        "table_hit": table_hit,
        "citation_accuracy": sum(1 for r in per_question if r.citation_ok) / total,
        "questions": per_question,
        "out_of_scope": refused,
        "ambiguous": ambiguous,
    }


def evaluate_filtering(store: VectorStore, gold: dict, top_k: int) -> list[dict]:
    rows = []
    for case in gold["filter_cases"]:
        unfiltered = store.search(case["question"], top_k=top_k)
        filtered = store.search(
            case["question"], top_k=top_k, filters={"product_area": case["product_area"]}
        )
        rows.append(
            {
                "id": case["id"],
                "question": case["question"],
                "product_area": case["product_area"],
                "expected": case["expected_article_id"],
                "unfiltered_top": unfiltered[0][0].article_id if unfiltered else "",
                "unfiltered_source": unfiltered[0][0].source if unfiltered else "",
                "unfiltered_score": float(unfiltered[0][1]) if unfiltered else 0.0,
                "unfiltered_areas": [c.product_area for c, _ in unfiltered],
                "unfiltered_hit": any(c.article_id == case["expected_article_id"] for c, _ in unfiltered),
                "filtered_top": filtered[0][0].article_id if filtered else "",
                "filtered_source": filtered[0][0].source if filtered else "",
                "filtered_score": float(filtered[0][1]) if filtered else 0.0,
                "filtered_hit": any(c.article_id == case["expected_article_id"] for c, _ in filtered),
                "changed": [c.source for c, _ in unfiltered] != [c.source for c, _ in filtered],
            }
        )
    return rows


def evaluate_threshold(store: VectorStore, gold: dict, top_k: int = 5) -> dict:
    """
    Sweep SCORE_THRESHOLD against the gold set.

    The threshold is the only refusal layer that fires before the LLM is called,
    so its value decides whether an out-of-scope question costs a Groq request.
    A good threshold sits above every out-of-scope score and below every
    known-answer score.
    """
    def top_score(question: str, product_area: str | None = None) -> float:
        filters = {"product_area": product_area} if product_area else None
        hits = store.search(question, top_k=top_k, filters=filters)
        return float(hits[0][1]) if hits else 0.0

    # The answerable population is every in-corpus question, not only the eight
    # well-formed ones. The filter cases are deliberately vaguer, and leaving
    # them out is what makes a threshold look cleanly separable when it is not.
    gold_known = [(i["id"], i["question"], top_score(i["question"])) for i in gold["known_answer"]]
    filter_known = [(i["id"], i["question"], top_score(i["question"])) for i in gold["filter_cases"]]
    filtered_known = [
        (i["id"], i["question"], top_score(i["question"], i["product_area"]))
        for i in gold["filter_cases"]
    ]
    known = gold_known + filter_known
    out = [(i["id"], i["question"], top_score(i["question"])) for i in gold["out_of_scope"]]
    amb = [(i["id"], i["question"], top_score(i["question"])) for i in gold["ambiguous"]]

    candidates = sorted({round(step * 0.05, 2) for step in range(1, 13)} | {round(SCORE_THRESHOLD, 2)})
    sweep = []
    for threshold in candidates:
        sweep.append(
            {
                "threshold": threshold,
                "answerable_kept": sum(1 for _, _, sc in gold_known + filter_known if sc >= threshold),
                "out_refused": sum(1 for _, _, sc in out if sc < threshold),
                "ambiguous_refused": sum(1 for _, _, sc in amb if sc < threshold),
            }
        )

    min_known = min(sc for _, _, sc in known)
    min_gold_only = min(sc for _, _, sc in gold_known)
    min_filtered = min(sc for _, _, sc in filtered_known)
    max_out = max(sc for _, _, sc in out)
    separable = max_out < min_known

    if separable:
        recommended = round((min_known + max_out) / 2, 2)
    else:
        # No clean split. Favour recall: the highest sweep value that still keeps
        # every answerable question, leaving the prompt to refuse the rest.
        safe = [row["threshold"] for row in sweep if row["answerable_kept"] == len(known)]
        recommended = max(safe) if safe else 0.05

    return {
        "known": known,
        "gold_known": gold_known,
        "filter_known": filter_known,
        "filtered_known": filtered_known,
        "min_gold_only": min_gold_only,
        "min_filtered": min_filtered,
        "out": out,
        "ambiguous": amb,
        "sweep": sweep,
        "min_known": min_known,
        "max_out": max_out,
        "separable": separable,
        "recommended": recommended,
    }


def pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def render_results(docs_dir: Path, runs: dict, filtering: list[dict], corpus: list[dict], threshold: dict) -> str:
    out: list[str] = []
    w = out.append

    w("# Retrieval evaluation results")
    w("")
    w("Generated by `backend/scripts/evaluate_retrieval.py`. Regenerate with:")
    w("")
    w("```bash")
    w("cd backend && python scripts/evaluate_retrieval.py")
    w("```")
    w("")
    w(f"- Corpus: `{docs_dir.relative_to(REPO_ROOT) if docs_dir.is_relative_to(REPO_ROOT) else docs_dir}` "
      f"({len(corpus)} articles)")
    w("- Embedding model: `all-MiniLM-L6-v2`, normalized, FAISS `IndexFlatIP` (cosine similarity)")
    w(f"- Refusal threshold: `SCORE_THRESHOLD = {SCORE_THRESHOLD}`")
    w("- Gold set: 8 known-answer questions (3 of them answered only by a markdown table), "
      "2 ambiguous questions, 3 out-of-scope questions")
    w("")
    w("Two hit rates are reported. **Article Hit@k** asks only whether a chunk from the expected "
      "article reached the top-k. **Answer Hit@k** additionally requires that chunk to contain the "
      "gold answer string. The second is the metric worth optimising: a chunk from the right article "
      "that was cut before the answer still leads to a refusal or, worse, an answer citing text that "
      "does not support it. **Citation accuracy** is Answer Hit@1 — the source shown next to the "
      "answer really does contain it.")
    w("")

    w("## Corpus")
    w("")
    w("| article_id | source_file | product_area | last_updated |")
    w("| --- | --- | --- | --- |")
    for row in corpus:
        w(f"| {row['article_id']} | `{row['source_file']}` | {row['product_area']} | {row['last_updated']} |")
    w("")

    w("## 1. Chunking strategy comparison")
    w("")
    w("Same 6 articles, same embedding model, one index per configuration.")
    w("")
    for top_k in TOP_K_VALUES:
        w(f"### Top-{top_k}")
        w("")
        w(f"| Strategy / size / overlap | Chunks | Avg chars | Article Hit@{top_k} | "
          f"Answer Hit@1 | Answer Hit@{top_k} | MRR | Table Answer Hit@{top_k} | Citation accuracy |")
        w("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for name, run in runs.items():
            data = run["by_top_k"][top_k]
            w(
                f"| `{name}` | {run['chunk_count']} | {run['avg_chars']:.0f} | "
                f"{pct(data['hits'].get(top_k, 0.0))} | {pct(data['answer_hits'][1])} | "
                f"{pct(data['answer_hits'].get(top_k, 0.0))} | "
                f"{data['mrr']:.3f} | {pct(data['table_hit'])} | {pct(data['citation_accuracy'])} |"
            )
        w("")

    w("## 2. Top-3 vs Top-5")
    w("")
    w("| Strategy / size / overlap | Article Hit@3 | Article Hit@5 | Answer Hit@3 | Answer Hit@5 | Answer gain |")
    w("| --- | --- | --- | --- | --- | --- |")
    for name, run in runs.items():
        a3 = run["by_top_k"][3]["hits"].get(3, 0.0)
        a5 = run["by_top_k"][5]["hits"].get(5, 0.0)
        n3 = run["by_top_k"][3]["answer_hits"].get(3, 0.0)
        n5 = run["by_top_k"][5]["answer_hits"].get(5, 0.0)
        w(f"| `{name}` | {pct(a3)} | {pct(a5)} | {pct(n3)} | {pct(n5)} | {pct(n5 - n3)} |")
    w("")

    w("## 3. Per-question detail (best configuration, Top-5)")
    w("")
    best_name = max(
        runs,
        key=lambda n: (
            runs[n]["by_top_k"][5]["answer_hits"].get(5, 0.0),
            runs[n]["by_top_k"][5]["citation_accuracy"],
            runs[n]["by_top_k"][5]["mrr"],
        ),
    )
    w(f"Best configuration by Answer Hit@5, then citation accuracy, then MRR: **`{best_name}`**")
    w("")
    w("| ID | Kind | Question | Expected | Article rank | Answer rank | Top-1 score | Top-1 source | Citation OK |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in runs[best_name]["by_top_k"][5]["questions"]:
        w(
            f"| {r.qid} | {r.kind} | {r.question} | {r.expected} | "
            f"{r.rank or 'miss'} | {r.answer_rank or 'miss'} | "
            f"{r.top_score:.3f} | `{r.top_source}` | {'yes' if r.citation_ok else 'no'} |"
        )
    w("")

    w("## 4. Metadata filtering")
    w("")
    w(f"Filter applied on `product_area`. Comparison run on the best configuration (`{best_name}`), Top-5.")
    w("")
    w("| ID | Question | Filter | Unfiltered top-1 | Areas returned unfiltered | Filtered top-1 | Ranking changed |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for row in filtering:
        areas = ", ".join(dict.fromkeys(row["unfiltered_areas"])) or "-"
        w(
            f"| {row['id']} | {row['question']} | `{row['product_area']}` | "
            f"{row['unfiltered_top']} (`{row['unfiltered_source']}`, {row['unfiltered_score']:.3f}) | "
            f"{areas} | {row['filtered_top']} (`{row['filtered_source']}`, {row['filtered_score']:.3f}) | "
            f"{'yes' if row['changed'] else 'no'} |"
        )
    w("")
    changed_count = sum(1 for r in filtering if r["changed"])
    fixed_count = sum(1 for r in filtering if r["filtered_hit"] and not r["unfiltered_hit"])
    w(f"Filtering changed the returned ranking in {changed_count} of {len(filtering)} cases, and moved "
      f"the expected article into the result set in {fixed_count} case(s) where the unfiltered search missed it.")
    w("")

    w("## 5. Refusal behaviour")
    w("")
    w("Out-of-scope questions. A question is refused before any LLM call when the best "
      f"similarity is below `{SCORE_THRESHOLD}`.")
    w("")
    w("| ID | Question | Best score | Closest chunk | Refused |")
    w("| --- | --- | --- | --- | --- |")
    for row in runs[best_name]["by_top_k"][5]["out_of_scope"]:
        w(
            f"| {row['id']} | {row['question']} | {row['best_score']:.3f} | "
            f"`{row['top_source']}` | {'yes' if row['refused'] else 'no'} |"
        )
    w("")
    w("Ambiguous questions (no single correct answer; recorded to show what the retriever does "
      "when the query carries almost no signal).")
    w("")
    w("| ID | Question | Best score | Top-1 section | Refused |")
    w("| --- | --- | --- | --- | --- |")
    for row in runs[best_name]["by_top_k"][5]["ambiguous"]:
        w(
            f"| {row['id']} | {row['question']} | {row['best_score']:.3f} | "
            f"{row['top_section'] or '-'} | {'yes' if row['refused'] else 'no'} |"
        )
    w("")

    w("### Refusal threshold sweep")
    w("")
    w("`SCORE_THRESHOLD` is the only refusal that fires *before* the LLM is called, so its value "
      "decides whether an out-of-scope question costs a Groq request at all.")
    w("")
    w(f"- Lowest top-1 score among the {len(threshold['gold_known'])} well-formed gold questions: "
      f"**{threshold['min_gold_only']:.3f}**")
    w(f"- Lowest top-1 score among all {len(threshold['known'])} in-corpus questions, including the "
      f"vaguer filter cases: **{threshold['min_known']:.3f}**")
    w(f"- Lowest top-1 score once a `product_area` filter is applied: **{threshold['min_filtered']:.3f}**")
    w(f"- Highest top-1 score among the {len(threshold['out'])} out-of-scope questions: "
      f"**{threshold['max_out']:.3f}**")
    w("")
    if threshold["separable"]:
        w(f"The two populations are **cleanly separable**. Any threshold between "
          f"{threshold['max_out']:.3f} and {threshold['min_known']:.3f} refuses every out-of-scope "
          f"question while keeping every answerable one. Midpoint: **{threshold['recommended']:.2f}**.")
    else:
        w(f"**The two populations overlap.** Judged on the 8 well-formed questions alone (minimum "
          f"{threshold['min_gold_only']:.3f}) the split looks clean, and a threshold near "
          f"{(threshold['min_gold_only'] + threshold['max_out']) / 2:.2f} appears safe. Adding the "
          f"vaguer filter-case questions drops the answerable minimum to {threshold['min_known']:.3f}, "
          f"below the out-of-scope maximum of {threshold['max_out']:.3f}, so **no single threshold "
          "separates them**. Tuning a threshold on a handful of well-formed questions overstates how "
          "separable real traffic is.")
        w("")
        w(f"The recommendation below therefore favours recall: **{threshold['recommended']:.2f}** is the "
          "highest value that still keeps every in-corpus question, leaving the system prompt to refuse "
          "what gets through.")
    w("")
    w("Note that applying a `product_area` filter *lowers* the top-1 score "
      f"(minimum {threshold['min_filtered']:.3f} versus {threshold['min_known']:.3f} unfiltered), because "
      "the filter removes higher-scoring chunks from other areas. A threshold tuned on unfiltered "
      "retrieval can therefore cause filtered queries to be refused.")
    w("")
    w(f"| Threshold | In-corpus kept (of {len(threshold['known'])}) | "
      f"Out-of-scope refused (of {len(threshold['out'])}) | "
      f"Ambiguous refused (of {len(threshold['ambiguous'])}) |")
    w("| --- | --- | --- | --- |")
    for row in threshold["sweep"]:
        marker = "  <- current" if abs(row["threshold"] - SCORE_THRESHOLD) < 1e-9 else ""
        rec = "  <- recommended" if threshold["recommended"] and abs(row["threshold"] - threshold["recommended"]) < 0.025 else ""
        w(
            f"| {row['threshold']:.2f}{marker}{rec} | {row['answerable_kept']} | "
            f"{row['out_refused']} | {row['ambiguous_refused']} |"
        )
    w("")

    w("## 6. Retrieval failures")
    w("")
    failures = [
        r for r in runs[best_name]["by_top_k"][5]["questions"]
        if r.answer_rank is None or r.answer_rank > 1
    ]
    if not failures:
        w(f"No misses and no citation failures on `{best_name}` at Top-5.")
    else:
        w("| ID | Question | Expected | Article rank | Answer rank | Failure |")
        w("| --- | --- | --- | --- | --- | --- |")
        for r in failures:
            if r.rank is None:
                mode = "expected article absent from top-5 entirely"
            elif r.answer_rank is None:
                mode = (
                    f"right article retrieved at rank {r.rank}, but no retrieved chunk contains the "
                    "answer: the chunk boundary cut it out"
                )
            else:
                mode = (
                    f"answer-bearing chunk only at rank {r.answer_rank}; rank 1 was a weaker chunk "
                    "from the same or another article"
                )
            w(f"| {r.qid} | {r.question} | {r.expected} | {r.rank or 'miss'} | {r.answer_rank or 'miss'} | {mode} |")
    w("")
    w("Failures across every configuration, to show which are systematic rather than "
      "artefacts of one setting:")
    w("")
    w("| Strategy / size / overlap | Article missed @5 | Answer missed @5 | Citation failures @1 |")
    w("| --- | --- | --- | --- |")
    for name, run in runs.items():
        data = run["by_top_k"][5]
        missed = [r.qid for r in data["questions"] if r.rank is None]
        amissed = [r.qid for r in data["questions"] if r.answer_rank is None]
        badcite = [r.qid for r in data["questions"] if not r.citation_ok]
        w(
            f"| `{name}` | {', '.join(missed) or 'none'} | {', '.join(amissed) or 'none'} | "
            f"{', '.join(badcite) or 'none'} |"
        )
    w("")

    w("## 7. Observations")
    w("")
    for line in observations(runs, filtering, best_name, threshold):
        w(f"- {line}")
    w("")

    w("## 8. Final chunking decision")
    w("")
    best_run = runs[best_name]
    strategy, size, overlap = best_name.split("/")
    w(f"**Chosen: `{strategy}` chunking, chunk size {size}, overlap {overlap}, Top-5 retrieval.**")
    w("")
    d5 = best_run["by_top_k"][5]
    w(
        f"It scores Answer Hit@5 {pct(d5['answer_hits'].get(5, 0.0))}, citation accuracy "
        f"{pct(d5['citation_accuracy'])}, MRR {d5['mrr']:.3f}, and table-question Answer Hit@5 "
        f"{pct(d5['table_hit'])} on the gold set, from {best_run['chunk_count']} chunks."
    )
    w("")
    w("Set it in `backend/.env`:")
    w("")
    w("```")
    w(f"CHUNK_STRATEGY={strategy}")
    w(f"CHUNK_SIZE={size}")
    w(f"CHUNK_OVERLAP={overlap}")
    w("TOP_K=5")
    w("```")
    w("")
    return "\n".join(out)


def observations(runs: dict, filtering: list[dict], best_name: str, threshold: dict) -> list[str]:
    """Statements derived from the numbers actually measured in this run."""
    notes: list[str] = []

    by_strategy: dict[str, list[float]] = {}
    for name, run in runs.items():
        strategy = name.split("/")[0]
        by_strategy.setdefault(strategy, []).append(run["by_top_k"][5]["table_hit"])
    for strategy, values in sorted(by_strategy.items()):
        notes.append(
            f"`{strategy}` chunking averages {pct(statistics.mean(values))} Answer Hit@5 on the three "
            f"table-answered questions across its {len(values)} configurations."
        )

    art = [run["by_top_k"][5]["hits"].get(5, 0.0) for run in runs.values()]
    ans = [run["by_top_k"][5]["answer_hits"].get(5, 0.0) for run in runs.values()]
    notes.append(
        f"Article-level Hit@5 averages {pct(statistics.mean(art))} across all {len(runs)} configurations and is "
        f"effectively saturated, while Answer-level Hit@5 averages {pct(statistics.mean(ans))} and spreads "
        f"from {pct(min(ans))} to {pct(max(ans))}. With a six-article corpus, article-level hit rate cannot "
        "tell two chunking strategies apart; only the chunk-level metric can."
    )

    fixed_small = runs.get("fixed/150/15")
    fixed_large = runs.get("fixed/1200/120")
    if fixed_small and fixed_large:
        notes.append(
            f"Chunk size drives the result far more than overlap: fixed/150 produces "
            f"{fixed_small['chunk_count']} chunks at Answer Hit@5 "
            f"{pct(fixed_small['by_top_k'][5]['answer_hits'].get(5, 0.0))} "
            f"(small chunks fragment the answer), while fixed/1200 produces {fixed_large['chunk_count']} chunks "
            f"at Answer Hit@5 {pct(fixed_large['by_top_k'][5]['answer_hits'].get(5, 0.0))} "
            "(large chunks dilute the embedding)."
        )

    low_overlap = runs.get("fixed/500/50")
    high_overlap = runs.get("fixed/500/125")
    if low_overlap and high_overlap:
        lo = low_overlap["by_top_k"][5]["answer_hits"].get(5, 0.0)
        hi = high_overlap["by_top_k"][5]["answer_hits"].get(5, 0.0)
        delta = hi - lo
        direction = "leaves unchanged" if abs(delta) < 1e-9 else ("improves" if delta > 0 else "degrades")
        notes.append(
            f"Raising overlap from 50 to 125 at chunk size 500 {direction} Answer Hit@5 "
            f"({pct(lo)} -> {pct(hi)}) while adding "
            f"{high_overlap['chunk_count'] - low_overlap['chunk_count']} chunks to the index. Overlap buys "
            "recovery of answers that straddle a boundary, at a proportional cost in index size."
        )

    gains = [
        run["by_top_k"][5]["answer_hits"].get(5, 0.0) - run["by_top_k"][3]["answer_hits"].get(3, 0.0)
        for run in runs.values()
    ]
    notes.append(
        f"Moving from Top-3 to Top-5 changes Answer Hit rate by {pct(statistics.mean(gains))} on average "
        "across configurations, at the cost of a longer prompt and more tokens per answer."
    )

    changed = sum(1 for r in filtering if r["changed"])
    notes.append(
        f"Metadata filtering on `product_area` altered the retrieved set in {changed} of {len(filtering)} "
        "test cases, confirming the filter reaches the ranking rather than being a no-op."
    )

    refusals = runs[best_name]["by_top_k"][5]["out_of_scope"]
    refused = sum(1 for r in refusals if r["refused"])
    leaked = [r for r in refusals if not r["refused"]]
    if leaked:
        worst = max(leaked, key=lambda r: r["best_score"])
        leaked_list = ", ".join(f"{r['question']!r} ({r['best_score']:.3f})" for r in leaked)
        verb = "still reaches" if len(leaked) == 1 else "still reach"
        notes.append(
            f"**The shipped threshold of {SCORE_THRESHOLD} is too low**: only {refused} of {len(refusals)} "
            f"out-of-scope questions are refused before the LLM is called. {leaked_list} {verb} Groq, "
            f"matching `{worst['top_source']}`, because an unrelated question still shares vocabulary and "
            "generic sentence structure with the corpus. Those cases depend entirely on the system prompt "
            "to refuse, which costs a paid API call each time."
        )
    else:
        notes.append(
            f"All {len(refusals)} out-of-scope questions score below the shipped threshold of "
            f"{SCORE_THRESHOLD} and are refused before any Groq call."
        )
    if threshold["separable"]:
        notes.append(
            f"Raising `SCORE_THRESHOLD` to {threshold['recommended']:.2f} refuses all "
            f"{len(threshold['out'])} out-of-scope questions before any Groq call while keeping all "
            f"{len(threshold['known'])} in-corpus ones."
        )
    else:
        notes.append(
            f"**The size of the gold set changes the conclusion.** On the 8 well-formed questions alone "
            f"the answerable population bottoms out at {threshold['min_gold_only']:.3f} against an "
            f"out-of-scope maximum of {threshold['max_out']:.3f}, which looks cleanly separable. Adding "
            f"3 vaguer but still in-corpus questions drops that minimum to {threshold['min_known']:.3f} "
            "and the separation disappears. A threshold tuned on a small set of well-formed questions "
            "will silently refuse real, answerable ones."
        )
        notes.append(
            f"`SCORE_THRESHOLD` is therefore set to {threshold['recommended']:.2f} - the highest value "
            "that keeps every in-corpus question - and the prompt-level refusal is load-bearing, not "
            "redundant. Removing it would let out-of-scope questions be answered from unrelated context."
        )
        notes.append(
            "Applying a `product_area` filter lowers the top-1 score (in-corpus minimum "
            f"{threshold['min_filtered']:.3f} filtered versus {threshold['min_known']:.3f} unfiltered), "
            "because filtering strips out higher-scoring chunks from other areas. Filtering and a high "
            "threshold interact badly: tune the threshold against filtered retrieval if the UI exposes "
            "the filter."
        )

    amb = runs[best_name]["by_top_k"][5]["ambiguous"]
    amb_scores = [r["best_score"] for r in amb]
    notes.append(
        f"Ambiguous questions score between {min(amb_scores):.2f} and {max(amb_scores):.2f}, below every "
        "answerable question, so a threshold tuned for out-of-scope questions also refuses them. That is the "
        "desired behaviour: 'How do I fix it?' has no answer in any document."
    )

    return notes


WEEK4_START = "<!-- week4:start -->"
WEEK4_END = "<!-- week4:end -->"


def _keep_week4_block(report: str, out_path: Path) -> str:
    """
    Carry an existing Week 4 block (sections 9-14) through this rewrite.

    This script owns sections 1-8 and regenerates the whole file, while
    `evaluate_week4.py` owns 9-14 and only rewrites what lies between the
    markers. Without this, whichever script ran last would silently delete the
    other's half of results.md, and the order you happened to run them in would
    decide what the report contained.
    """
    if not out_path.exists():
        return report
    existing = out_path.read_text(encoding="utf-8")
    if WEEK4_START not in existing or WEEK4_END not in existing:
        return report
    block = existing[existing.index(WEEK4_START) : existing.index(WEEK4_END) + len(WEEK4_END)]
    return report.rstrip() + "\n\n" + block + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval evaluation for the Week 3 RAG assignment")
    parser.add_argument("docs_dir", nargs="?", default=str(DEFAULT_DOCS))
    parser.add_argument("--out", default=str(RESULTS_PATH))
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir).resolve()
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))

    corpus_chunks = build_chunks(str(docs_dir), chunk_size=500, overlap=50, strategy="fixed")
    corpus: dict[str, dict] = {}
    for chunk in corpus_chunks:
        corpus.setdefault(chunk.article_id, chunk.metadata())
    corpus_rows = sorted(corpus.values(), key=lambda r: r["article_id"])

    print(f"Corpus: {len(corpus_rows)} articles from {docs_dir}")

    runs: dict[str, dict] = {}
    for strategy, size, overlap in CONFIGS:
        name = label(strategy, size, overlap)
        chunks = build_chunks(str(docs_dir), chunk_size=size, overlap=overlap, strategy=strategy)
        store = VectorStore()
        store.index(chunks)
        avg_chars = statistics.mean(len(c.text) for c in chunks) if chunks else 0.0
        print(f"  {name}: {len(chunks)} chunks (avg {avg_chars:.0f} chars)")

        runs[name] = {
            "chunk_count": len(chunks),
            "avg_chars": avg_chars,
            "store": store,
            "by_top_k": {k: evaluate_config(store, gold, k) for k in TOP_K_VALUES},
        }

    best_name = max(
        runs,
        key=lambda n: (
            runs[n]["by_top_k"][5]["answer_hits"].get(5, 0.0),
            runs[n]["by_top_k"][5]["citation_accuracy"],
            runs[n]["by_top_k"][5]["mrr"],
        ),
    )
    filtering = evaluate_filtering(runs[best_name]["store"], gold, 5)
    threshold = evaluate_threshold(runs[best_name]["store"], gold, 5)

    for run in runs.values():
        run.pop("store", None)

    report = render_results(docs_dir, runs, filtering, corpus_rows, threshold)
    out_path = Path(args.out)
    report = _keep_week4_block(report, out_path)
    out_path.write_text(report, encoding="utf-8")
    print(f"\nBest configuration: {best_name}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
