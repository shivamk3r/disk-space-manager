"""SQLite persistence for web jobs, reports, candidates, and actions."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .schemas import JobCreateRequest


DEFAULT_DB_PATH = Path.home() / ".disk-space-manager-web.sqlite3"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class WebRepository:
    """Small SQLite repository with one connection per operation."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()
        self.initialize()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    path TEXT NOT NULL,
                    age_months INTEGER NOT NULL,
                    include_duplicates INTEGER NOT NULL,
                    include_near_duplicates INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    progress_phase TEXT NOT NULL,
                    progress_percent REAL NOT NULL,
                    progress_message TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reports (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS candidates (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_candidates_job_kind
                    ON candidates(job_id, kind);

                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    action_type TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    target_path TEXT,
                    selected_count INTEGER NOT NULL,
                    skipped_count INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_job(self, job_id: str, request: JobCreateRequest, path: Path) -> Dict[str, Any]:
        created_at = utc_now()
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, status, path, age_months, include_duplicates,
                    include_near_duplicates, created_at, progress_phase,
                    progress_percent, progress_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    "queued",
                    str(path),
                    request.age_months,
                    int(request.include_duplicates),
                    int(request.include_near_duplicates),
                    created_at,
                    "queued",
                    0.0,
                    "Queued",
                ),
            )
        return self.get_job(job_id)

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def get_job(self, job_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return _row_to_job(row)

    def mark_job_running(self, job_id: str) -> None:
        with self._write() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, started_at = ?, progress_phase = ?,
                    progress_percent = ?, progress_message = ?
                WHERE id = ?
                """,
                ("running", utc_now(), "scan", 0.0, "Starting scan", job_id),
            )

    def update_job_progress(
        self,
        job_id: str,
        phase: str,
        percent: float,
        message: str,
    ) -> None:
        percent = max(0.0, min(float(percent), 100.0))
        with self._write() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET progress_phase = ?, progress_percent = ?, progress_message = ?
                WHERE id = ?
                """,
                (phase, percent, message, job_id),
            )

    def mark_job_completed(self, job_id: str) -> None:
        with self._write() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, finished_at = ?, progress_phase = ?,
                    progress_percent = ?, progress_message = ?
                WHERE id = ?
                """,
                ("completed", utc_now(), "complete", 100.0, "Complete", job_id),
            )

    def mark_job_failed(self, job_id: str, error: str) -> None:
        with self._write() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, finished_at = ?, error = ?, progress_phase = ?,
                    progress_message = ?
                WHERE id = ?
                """,
                ("failed", utc_now(), error, "failed", error, job_id),
            )

    def save_report(
        self,
        job_id: str,
        report: Dict[str, Any],
        candidates: Iterable[Dict[str, Any]],
    ) -> None:
        created_at = utc_now()
        candidate_rows = [
            (
                candidate["id"],
                job_id,
                candidate["kind"],
                candidate["path"],
                int(candidate["size"]),
                _json_dumps(candidate["metadata"]),
                created_at,
            )
            for candidate in candidates
        ]
        with self._write() as conn:
            conn.execute("DELETE FROM reports WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM candidates WHERE job_id = ?", (job_id,))
            conn.execute(
                """
                INSERT INTO reports (job_id, report_json, created_at)
                VALUES (?, ?, ?)
                """,
                (job_id, _json_dumps(report), created_at),
            )
            conn.executemany(
                """
                INSERT INTO candidates (
                    id, job_id, kind, path, size, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                candidate_rows,
            )

    def get_report(self, job_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT report_json FROM reports WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return json.loads(row["report_json"])

    def list_candidates(
        self,
        job_id: str,
        kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM candidates WHERE job_id = ?"
        params: List[Any] = [job_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY size DESC, path ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_candidate(row) for row in rows]

    def list_candidates_by_ids(
        self,
        job_id: str,
        candidate_ids: List[str],
        kind: str,
    ) -> List[Dict[str, Any]]:
        if not candidate_ids:
            return []
        placeholders = ",".join("?" for _ in candidate_ids)
        params: List[Any] = [job_id, kind] + list(candidate_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM candidates
                WHERE job_id = ? AND kind = ? AND id IN ({placeholders})
                """,
                params,
            ).fetchall()
        return [_row_to_candidate(row) for row in rows]

    def save_action(
        self,
        action_id: str,
        job_id: str,
        action_type: str,
        dry_run: bool,
        target_path: Optional[str],
        selected_count: int,
        skipped_count: int,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        created_at = utc_now()
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO actions (
                    id, job_id, action_type, dry_run, target_path,
                    selected_count, skipped_count, result_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    job_id,
                    action_type,
                    int(dry_run),
                    target_path,
                    selected_count,
                    skipped_count,
                    _json_dumps(result),
                    created_at,
                ),
            )
        return {
            "id": action_id,
            "job_id": job_id,
            "action_type": action_type,
            "dry_run": dry_run,
            "target_path": target_path,
            "selected_count": selected_count,
            "skipped_count": skipped_count,
            "result": result,
            "created_at": created_at,
        }

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return _ManagedConnection(conn)

    def _write(self):
        self._lock.acquire()
        try:
            conn = self._connect()
        except Exception:
            self._lock.release()
            raise
        return _LockedConnection(conn, self._lock)


class _ManagedConnection:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn.__enter__()

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.conn.__exit__(exc_type, exc, tb)
        finally:
            self.conn.close()


class _LockedConnection:
    def __init__(self, conn: _ManagedConnection, lock: threading.RLock):
        self.conn = conn
        self.lock = lock

    def __enter__(self) -> sqlite3.Connection:
        return self.conn.__enter__()

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.conn.__exit__(exc_type, exc, tb)
        finally:
            self.lock.release()


def _row_to_job(row: sqlite3.Row) -> Dict[str, Any]:
    job = dict(row)
    job["include_duplicates"] = bool(job["include_duplicates"])
    job["include_near_duplicates"] = bool(job["include_near_duplicates"])
    job["confirmation_phrases"] = {
        "clean": confirmation_phrase("clean", job["id"]),
        "archive": confirmation_phrase("archive", job["id"]),
    }
    return job


def _row_to_candidate(row: sqlite3.Row) -> Dict[str, Any]:
    candidate = dict(row)
    candidate["metadata"] = json.loads(candidate.pop("metadata_json"))
    return candidate


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def confirmation_phrase(action_type: str, job_id: str) -> str:
    return f"{action_type.upper()} {job_id[:8]}"
