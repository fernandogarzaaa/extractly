"""SQLite persistence for Extractly.

Tables:
    api_keys     one row per issued key. Only the SHA-256 hash is stored.
    usage_daily  per-key per-day extraction counters (UTC dates).
    requests     append-only log of extraction attempts (no raw text stored,
                 only sizes; reasoning traces are never persisted).
    key_events   audit log for key creation / upgrade / revocation.

WAL mode is enabled for concurrent readers. For production scale the
documented migration path is Postgres; the schema below maps 1:1.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash    TEXT NOT NULL UNIQUE,
    key_prefix  TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    tier        TEXT NOT NULL DEFAULT 'free',   -- 'free' | 'pro'
    revoked     INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_daily (
    key_id      INTEGER NOT NULL REFERENCES api_keys(id),
    day         TEXT NOT NULL,                  -- YYYY-MM-DD (UTC)
    count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, day)
);
CREATE TABLE IF NOT EXISTS requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id        INTEGER REFERENCES api_keys(id),
    ts            INTEGER NOT NULL,
    endpoint      TEXT NOT NULL,
    status        INTEGER NOT NULL,
    input_chars   INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    error         TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS key_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id     INTEGER REFERENCES api_keys(id),
    ts         INTEGER NOT NULL,
    event      TEXT NOT NULL,                  -- created | upgraded | revoked
    detail     TEXT NOT NULL DEFAULT '',
    ip         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_requests_key_ts ON requests(key_id, ts);
"""


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Store:
    """Thread-safe SQLite store. One instance per process."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # -- keys -----------------------------------------------------------
    def create_key(
        self, key_hash: str, key_prefix: str, label: str, ip: str = ""
    ) -> int:
        now = int(time.time())
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO api_keys (key_hash, key_prefix, label, tier, created_at)"
                " VALUES (?, ?, ?, 'free', ?)",
                (key_hash, key_prefix, label, now),
            )
            key_id = cur.lastrowid
            self._conn.execute(
                "INSERT INTO key_events (key_id, ts, event, ip)"
                " VALUES (?, ?, 'created', ?)",
                (key_id, now, ip),
            )
            self._conn.commit()
            return key_id

    def keys_created_from_ip_since(self, ip: str, since_ts: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM key_events"
                " WHERE event = 'created' AND ip = ? AND ts >= ?",
                (ip, since_ts),
            ).fetchone()
        return row[0]

    def get_key(self, key_hash: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, key_prefix, label, tier, revoked, created_at"
                " FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "prefix": row[1],
            "label": row[2],
            "tier": row[3],
            "revoked": bool(row[4]),
            "created_at": row[5],
        }

    def set_tier(self, key_id: int, tier: str, detail: str = "") -> None:
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                "UPDATE api_keys SET tier = ? WHERE id = ?", (tier, key_id)
            )
            self._conn.execute(
                "INSERT INTO key_events (key_id, ts, event, detail)"
                " VALUES (?, ?, 'upgraded', ?)",
                (key_id, now, detail),
            )
            self._conn.commit()

    # -- usage ----------------------------------------------------------
    def usage_today(self, key_id: int, day: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM usage_daily WHERE key_id = ? AND day = ?",
                (key_id, day),
            ).fetchone()
        return row[0] if row else 0

    def increment_usage(self, key_id: int, day: str) -> int:
        with self._lock:
            self._conn.execute(
                "INSERT INTO usage_daily (key_id, day, count) VALUES (?, ?, 1)"
                " ON CONFLICT(key_id, day) DO UPDATE SET count = count + 1",
                (key_id, day),
            )
            row = self._conn.execute(
                "SELECT count FROM usage_daily WHERE key_id = ? AND day = ?",
                (key_id, day),
            ).fetchone()
            self._conn.commit()
            return row[0]

    def keys_created_since(self, since_ts: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM api_keys WHERE created_at >= ?", (since_ts,)
            ).fetchone()
        return row[0]

    def requests_since(self, key_id: int, since_ts: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM requests WHERE key_id = ? AND ts >= ?",
                (key_id, since_ts),
            ).fetchone()
        return row[0]

    # -- request log ----------------------------------------------------
    def log_request(
        self,
        key_id: int | None,
        endpoint: str,
        status: int,
        input_chars: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
        error: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO requests (key_id, ts, endpoint, status, input_chars,"
                " prompt_tokens, completion_tokens, latency_ms, error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key_id,
                    int(time.time()),
                    endpoint,
                    status,
                    input_chars,
                    prompt_tokens,
                    completion_tokens,
                    latency_ms,
                    error[:500],
                ),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
