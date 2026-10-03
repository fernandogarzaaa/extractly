"""API key issuance and verification. Only SHA-256 hashes touch the database."""

from __future__ import annotations

import secrets

from .db import Store, hash_key

KEY_PREFIX = "ex_live_"
KEY_BYTES = 24  # 32 base64url-ish hex chars of entropy after the prefix


def issue_key(store: Store, label: str = "", ip: str = "") -> tuple[str, int]:
    """Creates a key, stores only its hash. Returns (raw_key, key_id).

    The raw key is shown exactly once to the caller; it is never stored.
    """
    raw = KEY_PREFIX + secrets.token_hex(KEY_BYTES)
    key_id = store.create_key(hash_key(raw), raw[:12], label[:80], ip=ip)
    return raw, key_id


def lookup_key(store: Store, raw: str) -> dict | None:
    """Returns the key record, or None if unknown/revoked."""
    if not raw or not raw.startswith(KEY_PREFIX):
        return None
    rec = store.get_key(hash_key(raw))
    if not rec or rec["revoked"]:
        return None
    return rec
