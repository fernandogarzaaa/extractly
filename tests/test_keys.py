"""Tests for key issuance: raw key shown once, only hash stored."""

from extractly import keys
from extractly.db import hash_key


def test_issue_and_lookup(store):
    raw, key_id = keys.issue_key(store, "mylabel", ip="2.2.2.2")
    assert raw.startswith("ex_live_")
    assert len(raw) > 20
    rec = keys.lookup_key(store, raw)
    assert rec is not None
    assert rec["id"] == key_id
    assert rec["label"] == "mylabel"


def test_raw_key_never_stored(store):
    raw, _ = keys.issue_key(store, "", ip="")
    # The database must not contain the raw key anywhere.
    stored_hash = hash_key(raw)
    rec = store.get_key(stored_hash)
    assert rec is not None
    assert raw not in stored_hash
    # A wrong key does not resolve.
    assert keys.lookup_key(store, raw + "x") is None


def test_lookup_rejects_bad_prefix(store):
    assert keys.lookup_key(store, "sk_live_whatever") is None
    assert keys.lookup_key(store, "") is None
    assert keys.lookup_key(store, None) is None


def test_keys_are_unique(store):
    raws = {keys.issue_key(store, "", ip="")[0] for _ in range(50)}
    assert len(raws) == 50
