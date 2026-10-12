"""
Follow-up questions: conversation history in, standalone question and suggestions out.

Both chats stay stateless. The browser sends the last few turns with every
request, and nothing about a conversation is stored here.

- `trim_history` caps what a client may send, so a long conversation cannot
  push a request past Groq's per-minute token limit.
- `rewrite_question` turns "how much does that one cost?" into a question that
  makes sense alone, for the RAG chat only. Retrieval searches with the latest
  message alone, so without the rewrite a follow-up finds nothing. The MCP
  agent gets the history as messages instead and writes its own tool queries.
- `suggest_follow_ups` proposes the other sections of the articles an answer
  cited. It needs no LLM call, and every suggestion is something the help
  centre can answer.

See docs/follow_up_questions.md.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# Three exchanges. Older turns rarely decide what "it" refers to, and every
# message here is resent to Groq on each request.
MAX_HISTORY_MESSAGES = 6
# Per message. Assistant answers can be long, and the rewrite only needs the gist.
MAX_HISTORY_CHARS = 1500
MAX_SUGGESTIONS = 3
# How many of the top-ranked cited sections count as "what was just answered".
# Not all of them: top-5 retrieval over a short article cites every section,
# and the low-ranked ones are exactly the related topics worth offering.
ANSWERED_SECTIONS = 2
# gpt-oss is a reasoning model: hidden reasoning tokens count against this, so
# it is far larger than a one-line question needs.
REWRITE_MAX_TOKENS = 600
# A "standalone question" longer than this is the model answering, not rewriting.
MAX_REWRITE_CHARS = 400

REWRITE_SYSTEM_PROMPT = """\
You rewrite the latest message in a customer-support conversation about AirFiber broadband \
into one standalone question that can be understood without the conversation. Replace \
pronouns and references such as "it", "that plan" or "the second one" with what they refer \
to. Keep plan names, error codes and ticket ids exactly as written. If the latest message is \
already a standalone question, or is not about the earlier conversation at all, return it \
unchanged. Do not answer the question. Reply with the question only, on one line."""


def trim_history(history: Optional[Iterable[Any]]) -> list[dict]:
    """The last MAX_HISTORY_MESSAGES non-empty turns as plain {role, content} dicts."""
    turns: list[dict] = []
    for turn in history or []:
        role = turn.get("role") if isinstance(turn, dict) else getattr(turn, "role", None)
        content = turn.get("content") if isinstance(turn, dict) else getattr(turn, "content", None)
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        content = content.strip()
        if len(content) > MAX_HISTORY_CHARS:
            content = content[:MAX_HISTORY_CHARS] + "…"
        turns.append({"role": role, "content": content})
    return turns[-MAX_HISTORY_MESSAGES:]


def rewrite_question(
    client: Any,
    model: str,
    question: str,
    history: list[dict],
    temperature: float | None = None,
) -> tuple[str, dict]:
    """
    Return (standalone question, info for the trace). Never raises: if the call
    fails or returns something unusable, the original question is searched, which
    is exactly what happened before follow-ups existed.
    """
    info: dict = {
        "original_question": question,
        "history_messages": len(history),
        "rewritten": False,
        "model": model,
        "error": None,
        "usage": None,
        "latency_ms": None,
    }
    if not history:
        return question, info

    transcript = "\n".join(
        f"{'Customer' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}" for turn in history
    )
    prompt = f"Conversation so far:\n{transcript}\n\nLatest message: {question}\n\nStandalone question:"
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=REWRITE_MAX_TOKENS,
            # Same convention as answer_with_groq: unset sends no temperature at all.
            **({} if temperature is None else {"temperature": temperature}),
        )
        raw = getattr(getattr(response.choices[0], "message", None), "content", None)
        usage = getattr(response, "usage", None)
        if usage is not None:
            info["usage"] = {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
    except Exception as exc:  # noqa: BLE001 - a failed rewrite must not fail the question
        logger.warning("Follow-up rewrite failed, searching the original question: %s", exc)
        info["error"] = f"{type(exc).__name__}: {exc}"
        return question, info
    finally:
        info["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)

    standalone = _clean(raw)
    if not standalone or len(standalone) > MAX_REWRITE_CHARS:
        info["error"] = "unusable rewrite"
        return question, info
    info["rewritten"] = standalone != question
    return standalone, info


def _clean(raw: Optional[str]) -> str:
    text = (raw or "").strip()
    text = text.splitlines()[0].strip() if text else ""
    for prefix in ("Standalone question:", "Question:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    return text.strip().strip('"').strip("'").strip()


def suggest_follow_ups(
    chunks: Iterable[Any],
    cited: Iterable[tuple[str, str]],
    limit: int = MAX_SUGGESTIONS,
) -> list[dict]:
    """
    Up to `limit` sections of the articles in `cited`, as {"label", "question"}
    dicts, in the order the articles were cited, skipping the sections the
    answer was about (the top ANSWERED_SECTIONS cited ones).

    `chunks` is the indexed store (anything with article_id, section). `cited` is
    (article_id, section) pairs from the answer, best first. The question repeats the full
    heading path, which is what each chunk is prefixed with, so it retrieves
    that section in both retrieval modes.
    """
    cited = [(a, s) for a, s in cited if a]
    if not cited:
        return []
    answered = {section for _, section in cited[:ANSWERED_SECTIONS]}
    sections_by_article: dict[str, list[str]] = {}
    for chunk in chunks:
        article_id = getattr(chunk, "article_id", "")
        section = getattr(chunk, "section", "")
        if not article_id or not section:
            continue
        bucket = sections_by_article.setdefault(article_id, [])
        if section not in bucket:
            bucket.append(section)

    suggestions: list[dict] = []
    seen: set[str] = set()
    for article_id in dict.fromkeys(a for a, _ in cited):
        for section in sections_by_article.get(article_id, []):
            path = [part.strip() for part in section.split(">") if part.strip()]
            # A bare article title is the intro paragraph, not a topic to offer.
            if len(path) < 2 or section in answered or section in seen:
                continue
            seen.add(section)
            leaf, article = path[-1], path[0]
            suggestions.append({"label": leaf, "question": f"Tell me about {leaf} ({article})"})
            if len(suggestions) >= limit:
                return suggestions
    return suggestions
