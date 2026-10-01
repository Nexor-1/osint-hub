"""SQLite persistence for scans, per-tool runs, findings and exported reports.

The database lives in ``%APPDATA%\\OSINTHub\\osinthub.db``. A single
connection is shared behind a lock: the scan engine writes from its worker
thread while the UI reads from the main thread.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..config import data_dir
from .schema import Finding, Status, ToolResult, utcnow

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target      TEXT NOT NULL,
    target_type TEXT NOT NULL,
    tools       TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    finished_at TEXT,
    parent_id   INTEGER REFERENCES scans(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS tool_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id        INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    tool           TEXT NOT NULL,
    status         TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT,
    error          TEXT,
    raw            TEXT,
    log            TEXT,
    findings_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (scan_id, tool)
);
CREATE TABLE IF NOT EXISTS findings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES tool_runs(id) ON DELETE CASCADE,
    scan_id    INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    tool       TEXT NOT NULL,
    type       TEXT NOT NULL,
    value      TEXT NOT NULL,
    source     TEXT NOT NULL,
    confidence TEXT NOT NULL,
    extra      TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id        INTEGER REFERENCES scans(id) ON DELETE SET NULL,
    title          TEXT NOT NULL,
    format         TEXT NOT NULL,
    path           TEXT NOT NULL,
    size           INTEGER NOT NULL DEFAULT 0,
    findings_count INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_runs_scan ON tool_runs(scan_id);
CREATE INDEX IF NOT EXISTS ix_findings_scan ON findings(scan_id);
CREATE INDEX IF NOT EXISTS ix_scans_created ON scans(created_at);
"""


@dataclass(slots=True)
class RunRecord:
    tool: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    findings_count: int = 0
    log: str = ""


@dataclass(slots=True)
class ScanRecord:
    id: int
    target: str
    target_type: str
    tools: list[str]
    status: str
    created_at: str
    finished_at: str | None
    parent_id: int | None
    findings_count: int = 0
    runs: dict[str, RunRecord] = field(default_factory=dict)
    results: dict[str, ToolResult] = field(default_factory=dict)


@dataclass(slots=True)
class ReportRecord:
    id: int
    scan_id: int | None
    title: str
    format: str
    path: str
    size: int
    findings_count: int
    created_at: str


def aggregate_status(statuses: Iterable[str]) -> str:
    """Overall scan status from its tool runs."""
    st = list(statuses)
    if not st:
        return Status.DONE.value
    if any(s in (Status.QUEUED.value, Status.RUNNING.value) for s in st):
        return Status.RUNNING.value
    if any(s == Status.DONE.value for s in st):
        return Status.DONE.value
    if all(s == Status.CANCELLED.value for s in st):
        return Status.CANCELLED.value
    return Status.ERROR.value


class Storage:
    """Thread-safe repository over the SQLite file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "osinthub.db"
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.execute("PRAGMA journal_mode = WAL")
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _tx(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, tuple(params))

    # ------------------------------------------------------------------ scans
    def create_scan(self, target: str, target_type: str, tools: list[str], parent_id: int | None = None) -> int:
        with self._lock:
            self._db.execute("BEGIN")
            try:
                cur = self._db.execute(
                    "INSERT INTO scans (target, target_type, tools, status, created_at, parent_id) VALUES (?,?,?,?,?,?)",
                    (target, target_type, json.dumps(tools), Status.QUEUED.value, utcnow(), parent_id))
                scan_id = int(cur.lastrowid)
                self._db.executemany(
                    "INSERT INTO tool_runs (scan_id, tool, status) VALUES (?,?,?)",
                    [(scan_id, t, Status.QUEUED.value) for t in tools])
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return scan_id

    def set_run_status(self, scan_id: int, tool: str, status: str, *, started_at: str | None = None) -> None:
        with self._lock:
            if started_at:
                self._tx("UPDATE tool_runs SET status=?, started_at=? WHERE scan_id=? AND tool=?",
                         (status, started_at, scan_id, tool))
            else:
                self._tx("UPDATE tool_runs SET status=? WHERE scan_id=? AND tool=?", (status, scan_id, tool))
            self._refresh_scan_status(scan_id)

    def reset_run(self, scan_id: int, tool: str) -> None:
        """Prepare a run for retry: drop old findings and mark it queued."""
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._reset_run_tx(scan_id, tool)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            self._refresh_scan_status(scan_id)

    def _reset_run_tx(self, scan_id: int, tool: str) -> None:
        self._db.execute("DELETE FROM findings WHERE scan_id=? AND tool=?", (scan_id, tool))
        self._db.execute(
            "INSERT INTO tool_runs (scan_id, tool, status) VALUES (?,?,?) "
            "ON CONFLICT(scan_id, tool) DO UPDATE SET status=excluded.status, started_at=NULL, "
            "finished_at=NULL, error=NULL, raw=NULL, log=NULL, findings_count=0",
            (scan_id, tool, Status.QUEUED.value))
        row = self._db.execute("SELECT tools FROM scans WHERE id=?", (scan_id,)).fetchone()
        tools = json.loads(row["tools"]) if row else []
        if tool not in tools:
            tools.append(tool)
        self._db.execute("UPDATE scans SET tools=?, finished_at=NULL WHERE id=?", (json.dumps(tools), scan_id))

    def save_result(self, scan_id: int, result: ToolResult, log: str = "") -> None:
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute(
                    "UPDATE tool_runs SET status=?, started_at=COALESCE(?, started_at), finished_at=?, error=?, "
                    "raw=?, log=?, findings_count=? WHERE scan_id=? AND tool=?",
                    (result.status, result.started_at, result.finished_at, result.error,
                     json.dumps(result.raw, ensure_ascii=False, default=str), log,
                     len(result.findings), scan_id, result.tool))
                run_id = self._db.execute("SELECT id FROM tool_runs WHERE scan_id=? AND tool=?",
                                          (scan_id, result.tool)).fetchone()["id"]
                self._db.execute("DELETE FROM findings WHERE run_id=?", (run_id,))
                self._db.executemany(
                    "INSERT INTO findings (run_id, scan_id, tool, type, value, source, confidence, extra) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    [(run_id, scan_id, result.tool, f.type, f.value, f.source, f.confidence,
                      json.dumps(f.extra, ensure_ascii=False, default=str)) for f in result.findings])
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            self._refresh_scan_status(scan_id)

    def _refresh_scan_status(self, scan_id: int) -> str:
        rows = self._tx("SELECT status FROM tool_runs WHERE scan_id=?", (scan_id,)).fetchall()
        status = aggregate_status(r["status"] for r in rows)
        finished = utcnow() if Status(status).is_final else None
        self._tx("UPDATE scans SET status=?, finished_at=? WHERE id=?", (status, finished, scan_id))
        return status

    def recover_interrupted(self) -> int:
        """Mark runs left queued/running by a previous crash or exit as errors."""
        with self._lock:
            cur = self._tx(
                "UPDATE tool_runs SET status=?, error=?, finished_at=? WHERE status IN (?,?)",
                (Status.ERROR.value, "Прервано: приложение было закрыто во время сканирования", utcnow(),
                 Status.QUEUED.value, Status.RUNNING.value))
            for row in self._tx("SELECT id FROM scans WHERE status IN (?,?)",
                                (Status.QUEUED.value, Status.RUNNING.value)).fetchall():
                self._refresh_scan_status(row["id"])
            return cur.rowcount

    def get_scan(self, scan_id: int, *, with_results: bool = True) -> ScanRecord | None:
        with self._lock:
            row = self._tx("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
            if not row:
                return None
            rec = self._scan_from_row(row)
            for r in self._tx("SELECT * FROM tool_runs WHERE scan_id=? ORDER BY id", (scan_id,)).fetchall():
                rec.runs[r["tool"]] = RunRecord(r["tool"], r["status"], r["started_at"], r["finished_at"],
                                                r["error"], r["findings_count"], r["log"] or "")
                rec.findings_count += r["findings_count"]
                if with_results:
                    rec.results[r["tool"]] = ToolResult(
                        tool=r["tool"], target=rec.target, status=r["status"],
                        started_at=r["started_at"], finished_at=r["finished_at"],
                        raw=json.loads(r["raw"]) if r["raw"] else None, error=r["error"],
                        target_type=rec.target_type)
            if with_results:
                for f in self._tx("SELECT * FROM findings WHERE scan_id=? ORDER BY id", (scan_id,)).fetchall():
                    res = rec.results.get(f["tool"])
                    if res is not None:
                        res.findings.append(Finding(f["type"], f["value"], f["source"], f["confidence"],
                                                    json.loads(f["extra"]) if f["extra"] else {}))
            return rec

    def list_scans(self, query: str = "", target_type: str | None = None, since: str | None = None,
                   limit: int = 500) -> list[ScanRecord]:
        sql = ("SELECT s.*, COALESCE((SELECT SUM(findings_count) FROM tool_runs r WHERE r.scan_id=s.id),0) AS fc "
               "FROM scans s WHERE 1=1")
        params: list[Any] = []
        if query:
            sql += " AND s.target LIKE ? ESCAPE '\\'"
            params.append("%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if target_type:
            sql += " AND s.target_type=?"
            params.append(target_type)
        if since:
            sql += " AND s.created_at >= ?"
            params.append(since)
        sql += " ORDER BY s.id DESC LIMIT ?"
        params.append(limit)
        out = []
        with self._lock:
            for row in self._tx(sql, params).fetchall():
                rec = self._scan_from_row(row)
                rec.findings_count = row["fc"]
                out.append(rec)
        return out

    def delete_scan(self, scan_id: int) -> None:
        self._tx("DELETE FROM scans WHERE id=?", (scan_id,))

    @staticmethod
    def _scan_from_row(row: sqlite3.Row) -> ScanRecord:
        return ScanRecord(row["id"], row["target"], row["target_type"], json.loads(row["tools"]),
                          row["status"], row["created_at"], row["finished_at"], row["parent_id"])

    # ---------------------------------------------------------------- reports
    def add_report(self, scan_id: int | None, title: str, fmt: str, path: str, size: int,
                   findings_count: int) -> int:
        cur = self._tx("INSERT INTO reports (scan_id, title, format, path, size, findings_count, created_at) "
                       "VALUES (?,?,?,?,?,?,?)", (scan_id, title, fmt, path, size, findings_count, utcnow()))
        return int(cur.lastrowid)

    def list_reports(self) -> list[ReportRecord]:
        rows = self._tx("SELECT * FROM reports ORDER BY id DESC").fetchall()
        return [ReportRecord(r["id"], r["scan_id"], r["title"], r["format"], r["path"], r["size"],
                             r["findings_count"], r["created_at"]) for r in rows]

    def delete_report(self, report_id: int) -> None:
        self._tx("DELETE FROM reports WHERE id=?", (report_id,))
