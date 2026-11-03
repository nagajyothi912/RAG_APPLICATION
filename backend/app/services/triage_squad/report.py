"""
report.py — Read and summarise a saved Week 10 race.

Shared by the race runner (which writes the markdown reports) and the
/api/week10 route (which serves the same numbers to the admin console), so
the page and race_table.md can never disagree. No LLM calls, no Groq client.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from app.services.ticket_reply_app.tickets import TICKETS
from app.services.triage_squad.metering import percentile

BACKEND = Path(__file__).resolve().parents[3]
ROOT = BACKEND.parent
EVAL_SET = BACKEND / "eval" / "week6" / "eval_set_25.jsonl"
OUT_DIR = ROOT / "eval" / "week10"
DOCS_DIR = ROOT / "docs" / "week10"
RESULTS = OUT_DIR / "race_results.json"

ARMS = ("single", "multi")
ARM_NAMES = {"single": "Single agent (Week 7 ReAct)", "multi": "Triage squad (orchestrator + 2 workers)"}
SINGLE_LOOP_HOP = "single agent loop"
SINGLE_REPLY_HOP = "single agent -> generate_ticket_reply"


def load_cases() -> List[Dict[str, Any]]:
    by_id = {}
    for line in EVAL_SET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            by_id[record["ticket_id"]] = record
    ids = [t["ticket_id"] for t in TICKETS]
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f"Week 7 ticket ids missing from the Week-6 eval set: {missing}")
    return [by_id[i] for i in ids]


def load_results() -> Dict[str, Any]:
    if RESULTS.exists():
        return json.loads(RESULTS.read_text(encoding="utf-8"))
    return {"meta": {}, "cases": {}, "failure_run": None}


def arm_summary(results: Dict[str, Any], cases: List[Dict[str, Any]], arm: str) -> Dict[str, Any]:
    runs = [results["cases"][c["ticket_id"]][arm] for c in cases]
    lat = [r["latency_ms"] for r in runs]
    lat_net = [r["latency_ms"] - r["rate_limit_wait_ms"] for r in runs]
    judged = [r["judge"] for r in runs if r.get("judge")]
    tokens = sum(r["total_tokens"] for r in runs)
    cost = sum(r["total_cost_usd"] for r in runs)
    return {
        "n": len(runs),
        "judged": len(judged),
        "passes": sum(j["pass"] for j in judged),
        "judge_passes": sum(j["score"] for j in judged),
        "assertion_passes": sum(all(j["assertions"].values()) for j in judged),
        "p50_ms": percentile(lat, 50),
        "p99_ms": percentile(lat, 99),
        "p50_net_ms": percentile(lat_net, 50),
        "p99_net_ms": percentile(lat_net, 99),
        "slowest": max(runs, key=lambda r: r["latency_ms"])["ticket_id"] if runs and "ticket_id" in runs[0] else None,
        "total_tokens": tokens,
        "prompt_tokens": sum(c["prompt_tokens"] for r in runs for c in r["calls"]),
        "completion_tokens": sum(c["completion_tokens"] for r in runs for c in r["calls"]),
        "llm_calls": sum(1 for r in runs for c in r["calls"] if c["kind"] != "hand-off"),
        "rejected_calls": sum(1 for r in runs for c in r["calls"] if c["kind"] == "rejected"),
        "cost_total": cost,
        "cost_per_ticket": cost / len(runs) if runs else 0.0,
        "rate_limit_wait_ms": sum(r["rate_limit_wait_ms"] for r in runs),
    }


def hop_shares(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_hop: Dict[str, Dict[str, Any]] = {}
    for r in runs:
        for c in r["calls"]:
            h = by_hop.setdefault(c["hop"], {"hop": c["hop"], "calls": 0, "prompt": 0, "completion": 0, "total": 0})
            if c["kind"] != "hand-off":
                h["calls"] += 1
            h["prompt"] += c["prompt_tokens"]
            h["completion"] += c["completion_tokens"]
            h["total"] += c["total_tokens"]
    grand = sum(h["total"] for h in by_hop.values()) or 1
    for h in by_hop.values():
        h["share"] = h["total"] / grand
    return sorted(by_hop.values(), key=lambda h: -h["total"])


def estimated_rejected_tokens(runs: List[Dict[str, Any]]) -> int:
    """
    Groq reports no usage for a rejected call, so those tokens are missing from
    the totals. Estimate each one at the mean size of its hop's successful calls.
    """
    sizes: Dict[str, List[int]] = defaultdict(list)
    for r in runs:
        for c in r["calls"]:
            if c["kind"] == "tool-calling":
                sizes[c["hop"]].append(c["total_tokens"])
    return round(sum(
        sum(sizes[c["hop"]]) / len(sizes[c["hop"]]) if sizes[c["hop"]] else 0
        for r in runs for c in r["calls"] if c["kind"] == "rejected"
    ))


def multiplier_line(single: Dict[str, Any], multi: Dict[str, Any], top: Dict[str, Any]) -> str:
    ratio = multi["total_tokens"] / single["total_tokens"] if single["total_tokens"] else float("nan")
    return (
        f"Context re-send multiplier: {multi['total_tokens']:,} / {single['total_tokens']:,} = **{ratio:.1f}x** "
        f"(squad tokens / single-agent tokens). Largest share: \"{top['hop']}\", "
        f"{top['share'] * 100:.0f}% of all squad tokens ({top['total']:,} tokens over {top['calls']} calls, "
        f"{top['prompt'] / max(top['total'], 1) * 100:.0f}% of them prompt tokens)."
    )


# ---------------------------------------------------------------------------
# The admin console payload (/api/week10/report)
# ---------------------------------------------------------------------------

def _plain_markdown(text: str) -> str:
    """Trim a hand-written doc to what the UI's RichText renders: no title, comments, links or backticks."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", "")
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _verdict(judge: Dict[str, Any] | None) -> Dict[str, Any]:
    if not judge:
        return {"pass": None, "judge_score": None, "judge_explanation": "", "failed_assertions": []}
    return {
        "pass": judge["pass"],
        "judge_score": judge["score"],
        "judge_explanation": judge["explanation"],
        "failed_assertions": [k for k, ok in judge["assertions"].items() if not ok],
    }


def _single_view(run: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_verdict(run.get("judge")),
        "reply": run["reply"],
        "total_tokens": run["total_tokens"],
        "cost_usd": run["total_cost_usd"],
        "latency_ms": run["latency_ms"],
        "tools_called": run.get("tools_called", []),
        "iterations": run.get("iterations"),
        "calls": run["calls"],
    }


def _multi_view(run: Dict[str, Any]) -> Dict[str, Any]:
    triage = run["triage"]["result"] or {}
    policy = run["policy"]["result"] or {}
    return {
        **_verdict(run.get("judge")),
        "reply": run["reply"],
        "total_tokens": run["total_tokens"],
        "cost_usd": run["total_cost_usd"],
        "latency_ms": run["latency_ms"],
        "plan": run["plan"],
        "triage_tools": triage.get("tools_called", []),
        "policy_tools": policy.get("tools_called", []),
        "escalated": triage.get("escalated"),
        "escalation_note": run.get("escalation_note", ""),
        "policy_attempts": run["policy"]["attempts"],
        "triage_attempts": run["triage"]["attempts"],
        "degraded": run["degraded"],
        "synthesis_context": run["synthesis_context"],
        "calls": run["calls"],
    }


def build_week10_report() -> Dict[str, Any]:
    results = load_results()
    if not results.get("cases"):
        return {"available": False}
    cases = load_cases()
    if any(arm not in results["cases"].get(c["ticket_id"], {}) for c in cases for arm in ARMS):
        return {"available": False, "reason": "The saved race is incomplete; resume it with the race command."}

    arms = {arm: arm_summary(results, cases, arm) for arm in ARMS}
    runs = {arm: [results["cases"][c["ticket_id"]][arm] for c in cases] for arm in ARMS}
    hops = {arm: hop_shares(runs[arm]) for arm in ARMS}
    est = {arm: estimated_rejected_tokens(runs[arm]) for arm in ARMS}
    single_tokens, multi_tokens = arms["single"]["total_tokens"], arms["multi"]["total_tokens"]
    top = hops["multi"][0]

    failure = None
    fr = results.get("failure_run")
    if fr:
        case = next(c for c in cases if c["ticket_id"] == fr["ticket_id"])
        doc = _read(DOCS_DIR / "failure_case.md")
        failure = {
            "ticket_id": fr["ticket_id"],
            "tier": case["tier"],
            "question": case["question"],
            "policy_context": case["context"],
            "worker_500s": fr.get("worker_500s", {}),
            "run": _multi_view({**fr["multi"], "judge": fr.get("judge")}),
            "clean_run": _multi_view(results["cases"][fr["ticket_id"]]["multi"]),
            "confirmed": _plain_markdown(doc.split("<!-- confirmed -->", 1)[1]) if "<!-- confirmed -->" in doc else "",
        }

    card = _read(DOCS_DIR / "agent_card.json")
    return {
        "available": True,
        "meta": {
            **{k: results["meta"].get(k) for k in ("model", "started_at", "judge_repeats", "fail_case", "judge_tokens")},
            "pricing_per_m": results["meta"].get("pricing_per_m"),
            "arm_names": ARM_NAMES,
        },
        "arms": arms,
        "multiplier": {
            "single_tokens": single_tokens,
            "multi_tokens": multi_tokens,
            "counted": multi_tokens / single_tokens if single_tokens else None,
            "estimated": (multi_tokens + est["multi"]) / max(single_tokens + est["single"], 1),
            "estimated_rejected_tokens": est,
            "top_hop": top,
            "line": multiplier_line(arms["single"], arms["multi"], top).replace("**", ""),
        },
        "hops": hops,
        "tickets": [
            {
                "ticket_id": c["ticket_id"],
                "tier": c["tier"],
                "tenure_days": c["tenure_days"],
                "refund_requested": c["refund_requested"],
                "question": c["question"],
                "context": c["context"],
                "single": _single_view(results["cases"][c["ticket_id"]]["single"]),
                "multi": _multi_view(results["cases"][c["ticket_id"]]["multi"]),
            }
            for c in cases
        ],
        "failure": failure,
        "verdict": _plain_markdown(_read(DOCS_DIR / "verdict.md")),
        "a2a_lifecycle": _plain_markdown(_read(DOCS_DIR / "a2a_lifecycle.md")),
        "agent_card": json.loads(card) if card else None,
    }
