"""
SQLite index over the trace log: the thing that makes a past answer findable.

The JSONL is the record; this is how you search it. A support complaint arrives
as "a wrong answer about refunds yesterday afternoon" - a time window, a topic
in the *answer*, and nothing else. Grepping a JSONL for that means opening
thousands of 8 KB lines. Here the same question is one query:

    find_trace.py --day yesterday --hours 12-18 --text refund

Both the question and the answer are indexed (full-text when SQLite has FTS5,
a LIKE scan when it does not), because a complaint describes the output and an
index over inputs alone finds nothing. The other slices a drill reaches for are
plain columns with indexes: time, user, prompt version, input type, cost.

Derived data only: `rebuild()` recreates the whole file from the JSONL, so a
lost or corrupt index is a nuisance and never a loss. This module is a leaf
(stdlib + app.config), like tracing.py, and `upsert` never raises into a request.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

_COLUMNS = (
    "trace_id TEXT PRIMARY KEY, started_at TEXT, user TEXT, role TEXT, session_id TEXT,"
    "prompt_version TEXT, prompt_id TEXT, input_type TEXT, mode TEXT, status TEXT,"
    "answer_source TEXT, model TEXT, total_ms REAL, cost_usd REAL, prompt_tokens INTEGER,"
    "completion_tokens INTEGER, cache_hit INTEGER, question TEXT, answer TEXT, context_ids TEXT"
)
_INDEXED = ("started_at", "user", "prompt_version", "input_type", "cost_usd", "status")


def _row(record: dict) -> Optional[tuple]:
    if record.get("event") != "chat" or not record.get("trace_id"):
        return None
    gen = record.get("generation") or {}
    sess = record.get("session") or {}
    tokens = record.get("tokens") or {}
    return (
        record["trace_id"],
        record.get("started_at"),
        sess.get("user", "anonymous"),
        sess.get("role", "unknown"),
        sess.get("session_id"),
        gen.get("prompt_version"),
        gen.get("prompt_id"),
        record.get("input_type", "question"),
        (record.get("request") or {}).get("mode_effective"),
        (record.get("outcome") or {}).get("status"),
        (record.get("answer") or {}).get("source"),
        gen.get("model"),
        (record.get("latency_ms") or {}).get("total"),
        (record.get("cost_usd") or {}).get("total"),
        tokens.get("prompt"),
        tokens.get("completion"),
        1 if (record.get("cache") or {}).get("hit") else 0,
        (record.get("request") or {}).get("question", ""),
        (record.get("answer") or {}).get("text", ""),
        " ".join(record.get("context_ids") or []),
    )


class TraceIndex:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._ready = False
        self.fts = False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        if not self._ready:
            conn.execute(f"CREATE TABLE IF NOT EXISTS traces ({_COLUMNS})")
            for col in _INDEXED:
                conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{col} ON traces({col})")
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS traces_fts USING fts5("
                    "question, answer, context_ids, content='traces', content_rowid='rowid')"
                )
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False
            conn.commit()
            self._ready = True
        else:
            self.fts = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='traces_fts'"
            ).fetchone() is not None
        return conn

    def upsert(self, record: dict) -> None:
        """Never raises: indexing is telemetry, not part of answering."""
        try:
            self.upsert_many([record])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Trace index write failed: %s", exc)

    def upsert_many(self, records: Iterable[dict]) -> int:
        rows = [r for r in (_row(rec) for rec in records) if r]
        if not rows:
            return 0
        with self._lock:
            conn = self._connect()
            try:
                for row in rows:
                    old = conn.execute(
                        "SELECT rowid, question, answer, context_ids FROM traces WHERE trace_id=?", (row[0],)
                    ).fetchone()
                    if old is not None and self.fts:
                        conn.execute(
                            "INSERT INTO traces_fts(traces_fts, rowid, question, answer, context_ids)"
                            " VALUES('delete', ?, ?, ?, ?)",
                            (old["rowid"], old["question"], old["answer"], old["context_ids"]),
                        )
                    conn.execute(
                        f"INSERT OR REPLACE INTO traces VALUES ({','.join('?' * len(row))})", row
                    )
                    if self.fts:
                        rid = conn.execute("SELECT rowid FROM traces WHERE trace_id=?", (row[0],)).fetchone()[0]
                        conn.execute(
                            "INSERT INTO traces_fts(rowid, question, answer, context_ids) VALUES(?,?,?,?)",
                            (rid, row[17], row[18], row[19]),
                        )
                conn.commit()
            finally:
                conn.close()
        return len(rows)

    def rebuild(self, jsonl: Path | str) -> int:
        """Drop and recreate the index from the JSONL log."""
        with self._lock:
            if self.path.exists():
                self.path.unlink()
            self._ready = False
        records = []
        with open(jsonl, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping an unparseable trace line")
        return self.upsert_many(records)

    def count(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                return conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
            finally:
                conn.close()

    def search(
        self,
        *,
        text: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        user: Optional[str] = None,
        prompt_version: Optional[str] = None,
        input_type: Optional[str] = None,
        status: Optional[str] = None,
        min_cost: Optional[float] = None,
        context: Optional[str] = None,
        order: str = "started_at DESC",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        where, args = [], []
        if since:
            where.append("t.started_at >= ?"); args.append(since)
        if until:
            where.append("t.started_at < ?"); args.append(until)
        if user:
            where.append("t.user = ?"); args.append(user)
        if prompt_version:
            where.append("t.prompt_version = ?"); args.append(prompt_version)
        if input_type:
            where.append("t.input_type = ?"); args.append(input_type)
        if status:
            where.append("t.status = ?"); args.append(status)
        if min_cost is not None:
            where.append("t.cost_usd >= ?"); args.append(min_cost)
        if context:
            where.append("t.context_ids LIKE ?"); args.append(f"%{context}%")
        if order not in {"started_at DESC", "cost_usd DESC", "total_ms DESC"}:
            order = "started_at DESC"
        with self._lock:
            conn = self._connect()
            try:
                if text and self.fts:
                    # Quote each word so punctuation in a complaint cannot be read as FTS syntax.
                    match = " ".join('"' + w.replace('"', "") + '"' for w in text.split())
                    sql = (
                        "SELECT t.* FROM traces t JOIN traces_fts f ON f.rowid = t.rowid"
                        " WHERE traces_fts MATCH ?" + "".join(f" AND {w}" for w in where)
                    )
                    args = [match] + args
                else:
                    if text:
                        for w in text.split():
                            where.append("(t.question LIKE ? OR t.answer LIKE ?)")
                            args += [f"%{w}%", f"%{w}%"]
                    sql = "SELECT t.* FROM traces t" + (" WHERE " + " AND ".join(where) if where else "")
                sql += f" ORDER BY t.{order} LIMIT ?"
                return [dict(r) for r in conn.execute(sql, [*args, limit]).fetchall()]
            finally:
                conn.close()

    def cost_percentile(self, pct: float = 0.95) -> Optional[float]:
        with self._lock:
            conn = self._connect()
            try:
                vals = [r[0] for r in conn.execute(
                    "SELECT cost_usd FROM traces WHERE cost_usd > 0 ORDER BY cost_usd").fetchall()]
            finally:
                conn.close()
        if not vals:
            return None
        return vals[min(len(vals) - 1, int(pct * len(vals)))]


_indexes: dict[str, TraceIndex] = {}


def index_for(jsonl_path: Path | str) -> TraceIndex:
    """The index that lives beside a given trace log (trace_index.db in the same folder)."""
    path = Path(jsonl_path).resolve().parent / "trace_index.db"
    key = str(path)
    if key not in _indexes:
        _indexes[key] = TraceIndex(path)
    return _indexes[key]
