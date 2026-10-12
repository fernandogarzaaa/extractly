"""SQLite persistence for Extractly.

Tables:
    api_keys     one row per issued key. Only the SHA-256 hash is stored.
    usage_daily  per-key per-day extraction counters (UTC dates).
    requests     append-only log of extraction attempts (no raw text stored,
                 only sizes; reasoning traces are never persisted).
    key_events   audit log for key creation / upgrade / revocation.
    license_seats which API keys each Gumroad license (hashed) has upgraded,
                 so one license cannot upgrade an unlimited number of keys.

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
CREATE TABLE IF NOT EXISTS license_seats (
    license_hash TEXT NOT NULL,                -- sha256 of the Gumroad license key
    key_id       INTEGER NOT NULL REFERENCES api_keys(id),
    ts           INTEGER NOT NULL,
    PRIMARY KEY (license_hash, key_id)
);
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

    def redeem_license(self, key_id: int, license_hash: str, seats: int) -> bool:
        """Bind a license to a key and set it to Pro, atomically.

        Returns True if the key now holds a seat on this license (newly bound,
        or already bound before), False if every seat is taken by other keys.
        """
        now = int(time.time())
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                bound = self._conn.execute(
                    "SELECT 1 FROM license_seats WHERE license_hash = ? AND key_id = ?",
                    (license_hash, key_id),
                ).fetchone()
                if not bound:
                    used = self._conn.execute(
                        "SELECT COUNT(*) FROM license_seats WHERE license_hash = ?",
                        (license_hash,),
                    ).fetchone()[0]
                    if used >= seats:
                        self._conn.rollback()
                        return False
                    self._conn.execute(
                        "INSERT INTO license_seats (license_hash, key_id, ts)"
                        " VALUES (?, ?, ?)",
                        (license_hash, key_id, now),
                    )
                self._conn.execute(
                    "UPDATE api_keys SET tier = 'pro' WHERE id = ?", (key_id,)
                )
                self._conn.execute(
                    "INSERT INTO key_events (key_id, ts, event, detail)"
                    " VALUES (?, ?, 'upgraded', ?)",
                    (key_id, now, "gumroad license verified"),
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    def license_seats_used(self, license_hash: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM license_seats WHERE license_hash = ?",
                (license_hash,),
            ).fetchone()
        return row[0]

    # -- usage ----------------------------------------------------------
    def reserve_usage(self, key_id: int, day: str, quota: int) -> int | None:
        """Atomically take one unit of today's quota.

        Returns the new count, or None if the quota is already used up. Callers
        that fail afterwards should call release_usage() to give it back.
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO usage_daily (key_id, day, count) VALUES (?, ?, 0)",
                (key_id, day),
            )
            cur = self._conn.execute(
                "UPDATE usage_daily SET count = count + 1"
                " WHERE key_id = ? AND day = ? AND count < ?",
                (key_id, day, quota),
            )
            if cur.rowcount != 1:
                self._conn.commit()
                return None
            row = self._conn.execute(
                "SELECT count FROM usage_daily WHERE key_id = ? AND day = ?",
                (key_id, day),
            ).fetchone()
            self._conn.commit()
            return row[0]

    def release_usage(self, key_id: int, day: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE usage_daily SET count = count - 1"
                " WHERE key_id = ? AND day = ? AND count > 0",
                (key_id, day),
            )
            self._conn.commit()

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
