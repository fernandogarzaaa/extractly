"""Tests for the SQLite store."""

from extractly.db import Store, hash_key


def test_create_and_lookup_key(store):
    key_id = store.create_key(hash_key("ex_live_abc"), "ex_live_abc"[:12], "lbl", ip="1.2.3.4")
    rec = store.get_key(hash_key("ex_live_abc"))
    assert rec is not None
    assert rec["id"] == key_id
    assert rec["tier"] == "free"
    assert rec["revoked"] is False
    assert rec["label"] == "lbl"


def test_unknown_key_returns_none(store):
    assert store.get_key(hash_key("ex_live_nope")) is None


def test_usage_counters(store):
    key_id = store.create_key(hash_key("k1"), "ex_live_", "", ip="")
    assert store.usage_today(key_id, "2026-10-03") == 0
    assert store.increment_usage(key_id, "2026-10-03") == 1
    assert store.increment_usage(key_id, "2026-10-03") == 2
    assert store.usage_today(key_id, "2026-10-03") == 2
    assert store.usage_today(key_id, "2026-10-04") == 0


def test_set_tier_and_events(store):
    key_id = store.create_key(hash_key("k2"), "ex_live_", "", ip="")
    store.set_tier(key_id, "pro", detail="test")
    rec = store.get_key(hash_key("k2"))
    assert rec["tier"] == "pro"


def test_keys_created_from_ip_since(store):
    assert store.keys_created_from_ip_since("9.9.9.9", 0) == 0
    store.create_key(hash_key("a"), "ex_live_", "", ip="9.9.9.9")
    store.create_key(hash_key("b"), "ex_live_", "", ip="9.9.9.9")
    store.create_key(hash_key("c"), "ex_live_", "", ip="1.1.1.1")
    assert store.keys_created_from_ip_since("9.9.9.9", 0) == 2
    assert store.keys_created_from_ip_since("1.1.1.1", 0) == 1
    assert store.keys_created_from_ip_since("9.9.9.9", 99999999999) == 0


def test_log_request_and_rate_window(store):
    key_id = store.create_key(hash_key("k3"), "ex_live_", "", ip="")
    assert store.requests_since(key_id, 0) == 0
    store.log_request(key_id, "POST /v1/extract", 200, input_chars=10)
    store.log_request(key_id, "POST /v1/extract", 200, input_chars=10)
    assert store.requests_since(key_id, 0) == 2
    assert store.requests_since(key_id, 99999999999) == 0
