"""
race.py — Week 10: race the triage squad against the single agent.

    cd backend
    python -m app.services.triage_squad.race                # race + failure run + judge + reports
    python -m app.services.triage_squad.race --report-only  # rebuild the reports from saved results

Fairness rules this script enforces:
  * Cases: the 10 Week 7 ticket ids, read from the Week-6 eval set
    (eval/week6/eval_set_25.jsonl), so both arms see the Week-6 record exactly.
  * Same model, temperature 0, same mock retrieval, same reply-writing tool.
  * Same judge as Week 6: judge_v2 plus the four deterministic assertions.
    A case passes only if every assertion holds and the judge scores it 1.
  * Both arms go through one MeteredClient, so tokens, cost and 429 waits are
    counted identically. Every LLM call counts, including the one inside
    generate_ticket_reply (Week 7's agent total left that one out).
  * The failure injection is a separate run on one case, so the race table
    stays clean.

Results are saved after every arm, so a run that hits the Groq daily cap can be
resumed by running the same command again. A run cut short by the quota is
never scored.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(__file__).resolve().parents[3]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import httpx
import uvicorn
from openai import OpenAI

from app.config import settings
from app.services.ticket_reply_app.agent import BudgetTracker, run_agent
from app.services.triage_squad.metering import (
    CURRENT_HOP,
    INPUT_COST_PER_TOKEN,
    OUTPUT_COST_PER_TOKEN,
    Ledger,
    MeteredClient,
    QuotaExhausted,
)
from app.services.triage_squad.orchestrator import DECOMPOSE_HOP, SYNTHESIS_HOP, run_orchestrator
from app.services.triage_squad.worker_api import POLICY_HOP, TRIAGE_HOP, FailureInjector, create_worker_app

from app.services.triage_squad.report import (
    ARM_NAMES,
    ARMS,
    DOCS_DIR,
    OUT_DIR,
    RESULTS,
    SINGLE_LOOP_HOP,
    SINGLE_REPLY_HOP,
    arm_summary,
    estimated_rejected_tokens,
    hop_shares,
    load_cases,
    load_results,
    multiplier_line,
)

JUDGE_PROMPT = BACKEND / "eval" / "week6" / "judge_v2.txt"
DEFAULT_FAIL_CASE = "T017"

# The Week 7 agent's 60s wall-clock budget would fire on Groq free-tier 429
# waits, which the race already measures separately. Its other three budgets
# stay at their Week 7 defaults.
SINGLE_WALL_CLOCK_S = 600.0


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Worker service
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_worker_server(app) -> tuple[str, uvicorn.Server]:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return f"http://127.0.0.1:{port}", server
        time.sleep(0.05)
    sys.exit("worker service did not start")


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------

def _critical_path_wait_ms(calls: List[Dict[str, Any]], arm: str) -> float:
    """Rate-limit wait on the wall clock. The squad's workers run in parallel, so only the longer one counts."""
    waits = defaultdict(float)
    for c in calls:
        waits[c["hop"]] += c.get("rate_limit_wait_ms", 0.0)
    if arm == "multi":
        return waits[DECOMPOSE_HOP] + max(waits[TRIAGE_HOP], waits[POLICY_HOP]) + waits[SYNTHESIS_HOP]
    return sum(waits.values())


def run_single(case: Dict[str, Any], raw_client: Any, model: str) -> Dict[str, Any]:
    client = MeteredClient(raw_client, Ledger())
    CURRENT_HOP.set(SINGLE_LOOP_HOP)
    t0 = time.perf_counter()
    result = run_agent(case, client, model, budget=BudgetTracker(max_wall_clock=SINGLE_WALL_CLOCK_S))
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    if client.quota_exhausted:
        raise QuotaExhausted("single agent run hit the Groq quota")
    calls = client.ledger.records
    for c in calls:  # the reply tool is the only call the agent makes without tools
        c["hop"] = SINGLE_LOOP_HOP if c["kind"] == "tool-calling" else SINGLE_REPLY_HOP
    return {
        "reply": result["reply"],
        "tools_called": result["tools_called"],
        "iterations": result["iterations"],
        "budget_hit": result["budget_hit"],
        "total_tokens": client.ledger.total_tokens,
        "agent_reported_tokens": result["total_tokens"],
        "total_cost_usd": client.ledger.total_cost,
        "latency_ms": latency_ms,
        "rate_limit_wait_ms": _critical_path_wait_ms(calls, "single"),
        "calls": calls,
    }


def run_multi(case: Dict[str, Any], raw_client: Any, model: str, http: httpx.Client) -> Dict[str, Any]:
    client = MeteredClient(raw_client, Ledger())
    result = run_orchestrator(case, client, model, http)
    result["rate_limit_wait_ms"] = _critical_path_wait_ms(result["calls"], "multi")
    return result


# ---------------------------------------------------------------------------
# Judge (the Week 6 one, imported rather than copied)
# ---------------------------------------------------------------------------

def judge_reply(case: Dict[str, Any], reply: str, client: Any, model: str, repeats: int) -> Dict[str, Any]:
    from evaluate_week6 import call_llm_judge, run_assertions

    prompt = JUDGE_PROMPT.read_text(encoding="utf-8")
    judged_case = {**case, "drafted_reply": reply}
    runs = [call_llm_judge(client, prompt, judged_case, model) for _ in range(repeats)]
    if any(r.get("error") for r in runs) and getattr(client, "quota_exhausted", False):
        raise QuotaExhausted("judge hit the Groq quota")
    votes = [r["score"] for r in runs]
    score = 1 if sum(votes) * 2 > len(votes) else 0
    assertions = run_assertions(case, reply)
    return {
        "score": score,
        "votes": votes,
        "explanation": next(r for r in runs if r["score"] == score)["explanation"],
        "judge_error": any(r.get("error") for r in runs),
        "assertions": assertions,
        "pass": score == 1 and all(assertions.values()),
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_results(results: Dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def _fmt_s(ms: float) -> str:
    return f"{ms / 1000:.1f} s"


def write_race_table(results: Dict[str, Any], cases: List[Dict[str, Any]]) -> str:
    s, m = (arm_summary(results, cases, a) for a in ARMS)
    shares = hop_shares([results["cases"][c["ticket_id"]]["multi"] for c in cases])
    single_shares = hop_shares([results["cases"][c["ticket_id"]]["single"] for c in cases])
    meta = results["meta"]
    mult = multiplier_line(s, m, shares[0])
    est = {a: estimated_rejected_tokens([results["cases"][c["ticket_id"]][a] for c in cases]) for a in ARMS}
    est_ratio = (m["total_tokens"] + est["multi"]) / max(s["total_tokens"] + est["single"], 1)

    def pr(x: Dict[str, Any]) -> str:
        return f"{x['passes']}/{x['judged']} ({x['passes'] / max(x['judged'], 1) * 100:.0f}%)"

    lines = [
        "# Week 10 race: single agent vs triage squad",
        "",
        "<!-- Generated by `python -m app.services.triage_squad.race` from eval/week10/race_results.json. Do not hand-edit. -->",
        "",
        f"**Cases (the same 10 Week-6 eval cases for both arms):** {', '.join(c['ticket_id'] for c in cases)} "
        "- the Week 7 ticket ids, read from `backend/eval/week6/eval_set_25.jsonl`.",
        f"**Model:** `{meta.get('model')}`, temperature 0. **Judge:** Week 6 `judge_v2.txt` "
        f"(majority of {meta.get('judge_repeats')}) **and** the four Week 6 assertions; a case passes only if both pass.",
        f"**Run:** {meta.get('started_at')}. **Pricing:** ${INPUT_COST_PER_TOKEN * 1e6:.2f}/M input, "
        f"${OUTPUT_COST_PER_TOKEN * 1e6:.2f}/M output (Groq, gpt-oss-120b).",
        "",
        "## The four numbers",
        "",
        f"| Metric | {ARM_NAMES['single']} | {ARM_NAMES['multi']} |",
        "|---|---|---|",
        f"| **Pass rate** (judge v2 + assertions) | {pr(s)} | {pr(m)} |",
        f"| **p50 latency** | {_fmt_s(s['p50_ms'])} | {_fmt_s(m['p50_ms'])} |",
        f"| **p99 latency** (n=10, so the slowest ticket) | {_fmt_s(s['p99_ms'])} | {_fmt_s(m['p99_ms'])} |",
        f"| **Total tokens** (10 tickets) | {s['total_tokens']:,} | {m['total_tokens']:,} |",
        f"| **Cost per ticket** | ${s['cost_per_ticket']:.6f} | ${m['cost_per_ticket']:.6f} |",
        "",
        "Supporting rows:",
        "",
        f"| | {ARM_NAMES['single']} | {ARM_NAMES['multi']} |",
        "|---|---|---|",
        f"| Judge v2 passes alone | {s['judge_passes']}/{s['judged']} | {m['judge_passes']}/{m['judged']} |",
        f"| All four assertions pass | {s['assertion_passes']}/{s['judged']} | {m['assertion_passes']}/{m['judged']} |",
        f"| p50 / p99 with Groq 429 waits removed | {_fmt_s(s['p50_net_ms'])} / {_fmt_s(s['p99_net_ms'])} "
        f"| {_fmt_s(m['p50_net_ms'])} / {_fmt_s(m['p99_net_ms'])} |",
        f"| Time spent in Groq 429 waits (all tickets) | {_fmt_s(s['rate_limit_wait_ms'])} | {_fmt_s(m['rate_limit_wait_ms'])} |",
        f"| LLM calls (all tickets) | {s['llm_calls']} | {m['llm_calls']} |",
        f"| of which rejected by Groq (400, tokens not reported) | {s['rejected_calls']} | {m['rejected_calls']} |",
        f"| Prompt / completion tokens | {s['prompt_tokens']:,} / {s['completion_tokens']:,} "
        f"| {m['prompt_tokens']:,} / {m['completion_tokens']:,} |",
        f"| Total cost (10 tickets) | ${s['cost_total']:.6f} | ${m['cost_total']:.6f} |",
        "",
        "## Multiplier",
        "",
        mult,
        "",
        f"Calls Groq rejected (400, no usage reported) are not in these totals: {s['rejected_calls']} single, "
        f"{m['rejected_calls']} squad. Estimating each at its hop's mean call size adds ~{est['single']:,} and "
        f"~{est['multi']:,} tokens, giving an estimated multiplier of **{est_ratio:.1f}x**. "
        "Either way the squad spent fewer tokens than the single agent.",
        "",
        "## Where the squad's tokens go (from handoffs.log)",
        "",
        "| Hand-off | LLM calls | Prompt | Completion | Total | Share |",
        "|---|---|---|---|---|---|",
        *[f"| {h['hop']} | {h['calls']} | {h['prompt']:,} | {h['completion']:,} | {h['total']:,} | {h['share'] * 100:.0f}% |"
          for h in shares],
        "",
        "Single agent, for comparison:",
        "",
        "| Step | LLM calls | Prompt | Completion | Total | Share |",
        "|---|---|---|---|---|---|",
        *[f"| {h['hop']} | {h['calls']} | {h['prompt']:,} | {h['completion']:,} | {h['total']:,} | {h['share'] * 100:.0f}% |"
          for h in single_shares],
        "",
        "## Per ticket",
        "",
        "| Ticket | Single: pass | tokens | latency | Squad: pass | tokens | latency | Squad tools (triage / policy) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in cases:
        r = results["cases"][c["ticket_id"]]
        si, mu = r["single"], r["multi"]

        def mark(x: Dict[str, Any]) -> str:
            j = x.get("judge")
            if not j:
                return "-"
            why = [] if j["score"] else ["judge"]
            why += [k for k, ok in j["assertions"].items() if not ok]
            return "PASS" if j["pass"] else f"FAIL ({', '.join(why)})"

        tri = (mu["triage"]["result"] or {}).get("tools_called", [])
        pol = (mu["policy"]["result"] or {}).get("tools_called", [])
        lines.append(
            f"| {c['ticket_id']} | {mark(si)} | {si['total_tokens']:,} | {_fmt_s(si['latency_ms'])} "
            f"| {mark(mu)} | {mu['total_tokens']:,} | {_fmt_s(mu['latency_ms'])} "
            f"| {', '.join(tri) or '-'} / {', '.join(pol) or '-'} |"
        )
    lines += [
        "",
        "Single-agent token counts include the LLM call inside `generate_ticket_reply`, which the Week 7 "
        "agent's own total left out; the agent-reported totals are kept in race_results.json as "
        "`agent_reported_tokens`.",
        "",
    ]
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "race_table.md").write_text("\n".join(lines), encoding="utf-8")
    return mult


def _log_lines(label: str, run: Dict[str, Any]) -> List[str]:
    out = []
    for i, c in enumerate(run["calls"], start=1):
        line = (
            f"[{label}] {i:>2}. {c['hop']:<40} {c['kind']:<12} status={c['status']:<9} "
            f"prompt={c['prompt_tokens']:>5} completion={c['completion_tokens']:>5} total={c['total_tokens']:>5} "
            f"latency_ms={c['latency_ms']:>8.1f} rl_wait_ms={c['rate_limit_wait_ms']:>7.1f}"
        )
        if c.get("error"):
            line += f" error={c['error']!r}"
        out.append(line)
    out.append(f"[{label}]     ticket total tokens={run['total_tokens']} cost_usd={run['total_cost_usd']:.6f} "
               f"latency_ms={run['latency_ms']:.1f}")
    return out


def write_handoffs_log(results: Dict[str, Any], cases: List[Dict[str, Any]], mult: str) -> None:
    lines = [
        "# handoffs.log - every LLM call and every hand-off of the triage squad, with its token count.",
        "# Generated by race.py from eval/week10/race_results.json. One line per call; hand-off failures",
        "# appear as kind=hand-off with 0 tokens. Worker calls are reported back by the worker service.",
        f"# Run: {results['meta'].get('started_at')}  model={results['meta'].get('model')}",
        "",
        "## Squad (race)",
    ]
    for c in cases:
        lines += _log_lines(c["ticket_id"], results["cases"][c["ticket_id"]]["multi"]) + [""]
    shares = hop_shares([results["cases"][c["ticket_id"]]["multi"] for c in cases])
    lines.append("## Squad totals per hand-off")
    for h in shares:
        lines.append(f"{h['hop']:<40} calls={h['calls']:>3} prompt={h['prompt']:>6} "
                     f"completion={h['completion']:>6} total={h['total']:>6} share={h['share'] * 100:5.1f}%")
    lines += ["", "## " + re.sub(r"\*\*", "", mult), ""]
    fr = results.get("failure_run")
    if fr:
        lines.append(f"## Failure run ({fr['ticket_id']}, policy worker forced to HTTP 500; not part of the race)")
        lines += _log_lines(fr["ticket_id"], fr["multi"]) + [""]
    lines.append("## Single agent (race), for comparison")
    for c in cases:
        lines += _log_lines(c["ticket_id"], results["cases"][c["ticket_id"]]["single"]) + [""]
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "handoffs.log").write_text("\n".join(lines), encoding="utf-8")


def classify_failure(fr: Dict[str, Any], case: Dict[str, Any]) -> str:
    """A first pass only; failure_case.md asks for it to be confirmed by reading the reply."""
    run = fr["multi"]
    if run["policy"]["ok"]:
        return "retried"
    reply = run["reply"].lower()
    hedges = ("i don't know", "i do not know", "unavailable", "unable to", "cannot confirm",
              "can't confirm", "not able to", "will confirm", "follow up", "get back to you")
    def figures(text: str) -> set:
        # Whole numbers only, and not the ticket id's digits (T017 is not "7").
        return set(re.findall(r"(?<![\w#])\d[\d,.]*\d|(?<![\w#])\d(?![\w])", text))

    policy_only_figures = figures(case["context"]) - figures(run["synthesis_context"] + case["question"])
    stated = sorted(policy_only_figures & figures(run["reply"]))
    if stated:
        return f"lied (states policy figures {', '.join(stated)} that only the failed worker could have supplied)"
    if any(h in reply for h in hedges):
        return "degraded"
    return "unclear - read the reply"


def write_failure_case(results: Dict[str, Any], cases: List[Dict[str, Any]]) -> None:
    fr = results.get("failure_run")
    if not fr:
        return
    case = next(c for c in cases if c["ticket_id"] == fr["ticket_id"])
    run = fr["multi"]
    clean = results["cases"][fr["ticket_id"]]["multi"]
    j = fr.get("judge") or {}
    attempts = "; ".join(f"attempt {a['attempt']}: HTTP {a['status']} after {a['elapsed_ms']:.0f} ms"
                         for a in run["policy"]["attempts"])
    lines = [
        f"# Failure case: policy-lookup worker returns HTTP 500 on {fr['ticket_id']}",
        "",
        "<!-- Facts generated by race.py; the behaviour line is confirmed by hand after reading the reply. -->",
        "",
        f"**Injected:** the worker service answers `POST /workers/policy` for {fr['ticket_id']} with HTTP 500 "
        "on every attempt, before spending any tokens. Triage and the orchestrator run normally. "
        "This is a separate run; the race table uses the clean run.",
        "",
        f"**Why {fr['ticket_id']}:** {case['tier']} tier, refund requested, a dependent chain in Week 7 - "
        "the case where answering without the policy is most expensive to get wrong.",
        "",
        "## What the orchestrator did",
        "",
        f"- Policy hand-off: {attempts}. Retries allowed: 1.",
        f"- Marked degraded: {', '.join(run['degraded']) or 'nothing'}.",
        f"- Triage: escalated={run['triage']['result'].get('escalated') if run['triage']['ok'] else 'n/a'}, "
        f"tools={', '.join((run['triage']['result'] or {}).get('tools_called', [])) or '-'}.",
        f"- Tokens: {run['total_tokens']:,} (clean run: {clean['total_tokens']:,}); "
        f"latency {_fmt_s(run['latency_ms'])} (clean run: {_fmt_s(clean['latency_ms'])}).",
        "",
        "Context handed to the synthesiser:",
        "",
        "```text",
        run["synthesis_context"],
        "```",
        "",
        "Reply sent to the customer:",
        "",
        "```text",
        run["reply"],
        "```",
        "",
        "For comparison, the policy the worker would have returned:",
        "",
        "```text",
        case["context"],
        "```",
        "",
        f"Judge v2: {'PASS' if j.get('score') else 'FAIL'} - {j.get('explanation', 'not judged')}  ",
        f"Assertions: {', '.join(k for k, ok in (j.get('assertions') or {}).items() if not ok) or 'all pass'}",
        "",
        "## Behaviour",
        "",
        f"Automatic first pass: **{classify_failure(fr, case)}**.",
        "",
    ]
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / "failure_case.md"
    # The confirmed line is hand-written below the generated part; keep it on a rebuild.
    marker = "<!-- confirmed -->"
    tail = ""
    if path.exists() and marker in path.read_text(encoding="utf-8"):
        tail = path.read_text(encoding="utf-8").split(marker, 1)[1]
    path.write_text("\n".join(lines) + (marker + tail if tail else ""), encoding="utf-8")


def write_reports(results: Dict[str, Any], cases: List[Dict[str, Any]]) -> str:
    mult = write_race_table(results, cases)
    write_handoffs_log(results, cases, mult)
    write_failure_case(results, cases)
    return mult


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Week 10: race the triage squad against the single agent")
    parser.add_argument("--model", default=settings.groq_model)
    parser.add_argument("--judge-repeats", type=int, default=1,
                        help="judge runs per reply (majority vote); Week 6 used 3, 1 saves quota")
    parser.add_argument("--fail-case", default=DEFAULT_FAIL_CASE)
    parser.add_argument("--pause", type=float, default=20.0,
                        help="seconds between runs so one arm's tokens do not eat the next arm's per-minute quota")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="discard saved results and start over")
    args = parser.parse_args()

    cases = load_cases()
    results = {"meta": {}, "cases": {}, "failure_run": None} if args.fresh else load_results()
    if args.report_only:
        print(write_reports(results, cases))
        return

    if not settings.api_key:
        sys.exit("GROQ_API_KEY is not set in backend/.env")
    raw = OpenAI(api_key=settings.api_key, base_url=settings.groq_base_url)
    results["meta"].setdefault("started_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    results["meta"].update({
        "model": args.model, "judge_repeats": args.judge_repeats, "fail_case": args.fail_case,
        "cases": [c["ticket_id"] for c in cases],
        "pricing_per_m": {"input": INPUT_COST_PER_TOKEN * 1e6, "output": OUTPUT_COST_PER_TOKEN * 1e6},
    })

    injector = FailureInjector()
    app = create_worker_app(raw, args.model, {c["ticket_id"]: c["context"] for c in cases}, injector)
    base_url, server = start_worker_server(app)
    http = httpx.Client(base_url=base_url, timeout=600.0)
    print(f"worker service at {base_url}; model={args.model}; cases={', '.join(c['ticket_id'] for c in cases)}")

    try:
        # 1. The race. Arm order alternates per case so neither arm always inherits a drained quota.
        for i, case in enumerate(cases):
            tid = case["ticket_id"]
            slot = results["cases"].setdefault(tid, {})
            order = ARMS if i % 2 == 0 else ARMS[::-1]
            for arm in order:
                if arm in slot:
                    continue
                run = run_single(case, raw, args.model) if arm == "single" else run_multi(case, raw, args.model, http)
                run["ticket_id"] = tid
                slot[arm] = run
                save_results(results)
                print(f"  {tid} {arm:<6} tokens={run['total_tokens']:>6} latency={_fmt_s(run['latency_ms']):>8} "
                      f"429-wait={_fmt_s(run['rate_limit_wait_ms'])}")
                time.sleep(args.pause)

        # 2. The failure run: one case, policy worker forced to 500.
        if not results.get("failure_run"):
            case = next(c for c in cases if c["ticket_id"] == args.fail_case)
            injector.policy_fail_on = {args.fail_case}
            run = run_multi(case, raw, args.model, http)
            injector.policy_fail_on = set()
            run["ticket_id"] = args.fail_case
            results["failure_run"] = {"ticket_id": args.fail_case, "multi": run, "worker_500s": injector.hits}
            save_results(results)
            print(f"  failure run {args.fail_case}: policy attempts={run['policy']['attempts']} degraded={run['degraded']}")
            time.sleep(args.pause)

        # 3. Judge every reply with the Week 6 judge.
        judge_client = MeteredClient(raw, Ledger())
        targets = [(results["cases"][c["ticket_id"]][arm], c) for c in cases for arm in ARMS]
        fr = results["failure_run"]
        targets.append((fr, next(c for c in cases if c["ticket_id"] == fr["ticket_id"])))
        for holder, case in targets:
            run = holder if "reply" in holder else holder["multi"]
            if holder.get("judge"):
                continue
            holder["judge"] = judge_reply(case, run["reply"], judge_client, args.model, args.judge_repeats)
            save_results(results)
            print(f"  judged {case['ticket_id']}: {'PASS' if holder['judge']['pass'] else 'FAIL'}")
        results["meta"]["judge_tokens"] = results["meta"].get("judge_tokens", 0) + judge_client.ledger.total_tokens
        save_results(results)
    except QuotaExhausted as exc:
        save_results(results)
        sys.exit(f"Stopped: {exc}. Progress is saved; run the same command again to resume.")
    finally:
        http.close()
        server.should_exit = True

    print()
    print(write_reports(results, cases))
    print(f"\nWrote {DOCS_DIR.relative_to(ROOT)}/race_table.md, handoffs.log, failure_case.md")


if __name__ == "__main__":
    main()
