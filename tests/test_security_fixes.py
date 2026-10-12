"""Regression tests for the Oct 2026 audit fixes: license reuse, atomic quota,
trusted-proxy client IP, and no backend error text in 502 responses."""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

from test_api import SCHEMA, auth, make_client  # noqa: E402

from extractly.app import _in_networks, _parse_networks, client_ip  # noqa: E402
from extractly.db import Store  # noqa: E402
from extractly.llm import LLMError  # noqa: E402


def _pro_client(cfg, monkeypatch, seats=1):
    import extractly.app as appmod

    cfg.gumroad_product_permalink = "some-product"
    cfg.license_seats = seats
    monkeypatch.setattr(appmod, "verify_license", lambda *a, **k: True)
    return make_client(cfg)


# -- license binding -------------------------------------------------------
def test_one_license_cannot_upgrade_a_second_key(cfg, monkeypatch):
    c = _pro_client(cfg, monkeypatch)
    k1 = c.post("/v1/keys").json()["key"]
    k2 = c.post("/v1/keys").json()["key"]
    assert c.post("/v1/upgrade", headers=auth(k1), json={"license_key": "LIC"}).status_code == 200
    r = c.post("/v1/upgrade", headers=auth(k2), json={"license_key": " LIC "})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "license_in_use"
    assert c.get("/v1/usage", headers=auth(k2)).json()["tier"] == "free"


def test_same_key_can_redeem_its_license_again(cfg, monkeypatch):
    c = _pro_client(cfg, monkeypatch)
    k1 = c.post("/v1/keys").json()["key"]
    for _ in range(2):
        r = c.post("/v1/upgrade", headers=auth(k1), json={"license_key": "LIC"})
        assert r.status_code == 200 and r.json()["tier"] == "pro"


def test_license_seats_are_configurable(cfg, monkeypatch):
    c = _pro_client(cfg, monkeypatch, seats=2)
    keys = [c.post("/v1/keys").json()["key"] for _ in range(3)]
    codes = [
        c.post("/v1/upgrade", headers=auth(k), json={"license_key": "LIC"}).status_code
        for k in keys
    ]
    assert codes == [200, 200, 409]


def test_different_licenses_are_independent(cfg, monkeypatch):
    c = _pro_client(cfg, monkeypatch)
    k1 = c.post("/v1/keys").json()["key"]
    k2 = c.post("/v1/keys").json()["key"]
    assert c.post("/v1/upgrade", headers=auth(k1), json={"license_key": "A"}).status_code == 200
    assert c.post("/v1/upgrade", headers=auth(k2), json={"license_key": "B"}).status_code == 200


def test_store_keeps_only_license_hash(store):
    kid = store.create_key("h1", "ex_1", "")
    assert store.redeem_license(kid, "deadbeef", 1) is True
    assert store.license_seats_used("deadbeef") == 1
    assert store.get_key("h1")["tier"] == "pro"
    rows = store._conn.execute("SELECT license_hash FROM license_seats").fetchall()
    assert rows == [("deadbeef",)]


def test_refused_redeem_leaves_tier_and_seats_unchanged(store):
    a = store.create_key("ha", "ex_a", "")
    b = store.create_key("hb", "ex_b", "")
    assert store.redeem_license(a, "L", 1) is True
    assert store.redeem_license(b, "L", 1) is False
    assert store.get_key("hb")["tier"] == "free"
    assert store.license_seats_used("L") == 1
    assert store.license_seats_used("other") == 0


# -- atomic quota ------------------------------------------------------------
def test_reserve_usage_stops_at_quota(store):
    kid = store.create_key("h", "ex_", "")
    assert [store.reserve_usage(kid, "2026-10-12", 3) for _ in range(4)] == [1, 2, 3, None]
    assert store.usage_today(kid, "2026-10-12") == 3
    assert store.reserve_usage(kid, "2026-10-13", 3) == 1


def test_release_usage_gives_unit_back_and_never_goes_negative(store):
    kid = store.create_key("h", "ex_", "")
    store.reserve_usage(kid, "d", 1)
    store.release_usage(kid, "d")
    assert store.usage_today(kid, "d") == 0
    store.release_usage(kid, "d")
    assert store.usage_today(kid, "d") == 0
    assert store.reserve_usage(kid, "d", 1) == 1


def test_concurrent_reservations_never_exceed_quota(tmp_path):
    st = Store(tmp_path / "c.db")
    kid = st.create_key("h", "ex_", "")
    results = []
    barrier = threading.Barrier(16)

    def worker():
        barrier.wait()
        for _ in range(5):
            results.append(st.reserve_usage(kid, "d", 25))

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    granted = [r for r in results if r is not None]
    assert len(granted) == 25 and sorted(granted) == list(range(1, 26))
    assert st.usage_today(kid, "d") == 25
    st.close()


def test_failed_extraction_does_not_consume_quota(cfg):
    c = make_client(cfg, [LLMError("boom secret-upstream-detail")])
    key = c.post("/v1/keys").json()["key"]
    r = c.post("/v1/extract", headers=auth(key), json={"text": "t", "schema": SCHEMA})
    assert r.status_code == 502
    assert "secret-upstream-detail" not in r.text
    assert c.get("/v1/usage", headers=auth(key)).json()["used_today"] == 0


def test_422_extraction_does_not_consume_quota(cfg):
    c = make_client(cfg, [("garbage", (1, 1)), ("garbage", (1, 1))])
    key = c.post("/v1/keys").json()["key"]
    r = c.post("/v1/extract", headers=auth(key), json={"text": "t", "schema": SCHEMA})
    assert r.status_code == 422
    assert c.get("/v1/usage", headers=auth(key)).json()["used_today"] == 0


def test_invalid_body_does_not_consume_quota_or_call_llm(cfg):
    c = make_client(cfg)
    key = c.post("/v1/keys").json()["key"]
    r = c.post("/v1/extract", headers=auth(key), json={"text": "", "schema": SCHEMA})
    assert r.status_code == 400
    assert c.get("/v1/usage", headers=auth(key)).json()["used_today"] == 0
    assert c.fake.calls == 0


def test_quota_exceeded_skips_llm(cfg):
    c = make_client(cfg, [('{"vendor":"A","total":1}', (1, 1))] * cfg.free_daily_quota)
    key = c.post("/v1/keys").json()["key"]
    for _ in range(cfg.free_daily_quota):
        assert c.post("/v1/extract", headers=auth(key), json={"text": "t", "schema": SCHEMA}).status_code == 200
    r = c.post("/v1/extract", headers=auth(key), json={"text": "t", "schema": SCHEMA})
    assert r.status_code == 429
    assert c.fake.calls == cfg.free_daily_quota
    assert r.json()["error"]["code"] == "quota_exceeded"


def test_success_reports_reserved_count(cfg):
    c = make_client(cfg, [('{"vendor":"A","total":1}', (1, 1))] * 2)
    key = c.post("/v1/keys").json()["key"]
    r1 = c.post("/v1/extract", headers=auth(key), json={"text": "t", "schema": SCHEMA})
    r2 = c.post("/v1/extract", headers=auth(key), json={"text": "t", "schema": SCHEMA})
    assert r1.json()["quota"]["used_today"] == 1
    assert r2.json()["quota"] == {"used_today": 2, "quota_daily": cfg.free_daily_quota}


# -- trusted-proxy client IP -------------------------------------------------
def _req(peer, xff=None):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_xff_ignored_without_trusted_proxies():
    assert client_ip(_req("203.0.113.9", "1.2.3.4"), []) == "203.0.113.9"


def test_xff_ignored_from_untrusted_peer():
    nets = _parse_networks("127.0.0.1")
    assert client_ip(_req("203.0.113.9", "1.2.3.4"), nets) == "203.0.113.9"


def test_xff_used_from_trusted_peer_rightmost_untrusted_hop():
    nets = _parse_networks("127.0.0.1, 10.0.0.0/8")
    # client spoofed "6.6.6.6"; real client 198.51.100.7 appended by our proxy chain
    req = _req("127.0.0.1", "6.6.6.6, 198.51.100.7, 10.1.2.3")
    assert client_ip(req, nets) == "198.51.100.7"


def test_all_hops_trusted_falls_back_to_peer():
    nets = _parse_networks("127.0.0.1,10.0.0.0/8")
    assert client_ip(_req("127.0.0.1", "10.0.0.5"), nets) == "127.0.0.1"
    assert client_ip(_req("127.0.0.1", ""), nets) == "127.0.0.1"
    assert client_ip(_req("127.0.0.1"), nets) == "127.0.0.1"


def test_no_client_is_unknown():
    req = SimpleNamespace(client=None, headers={})
    assert client_ip(req, []) == "unknown"


def test_parse_networks_skips_garbage():
    nets = _parse_networks(" , nope, 192.168.0.0/16 ,::1")
    assert len(nets) == 2
    assert _in_networks("192.168.4.4", nets)
    assert _in_networks("::1", nets)
    assert not _in_networks("8.8.8.8", nets)
    assert not _in_networks("not-an-ip", nets)


def test_key_rate_limit_uses_forwarded_ip_behind_trusted_proxy(cfg):
    cfg.key_create_per_hour = 1
    cfg.trusted_proxies = "testclient"  # not an IP: ignored, so XFF is not trusted
    c = make_client(cfg)
    assert c.post("/v1/keys", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert c.post("/v1/keys", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429



# -- persistence / failure paths (mutation-testing follow-ups) ---------------
def test_reservations_and_redeems_are_committed(tmp_path):
    path = tmp_path / "p.db"
    st = Store(path)
    kid = st.create_key("h", "ex_", "")
    st.reserve_usage(kid, "d", 5)
    st.reserve_usage(kid, "d", 5)
    st.release_usage(kid, "d")
    assert st.redeem_license(kid, "L", 1) is True
    other = Store(path)  # separate connection only sees committed data
    assert other.usage_today(kid, "d") == 1
    assert other.license_seats_used("L") == 1
    assert other.get_key("h")["tier"] == "pro"
    events = other._conn.execute(
        "SELECT event, detail FROM key_events WHERE key_id = ? AND event = 'upgraded'", (kid,)
    ).fetchall()
    assert events == [("upgraded", "gumroad license verified")]
    other.close()
    st.close()


def test_quota_refusal_is_committed_and_visible(tmp_path):
    path = tmp_path / "q.db"
    st = Store(path)
    kid = st.create_key("h", "ex_", "")
    assert st.reserve_usage(kid, "d", 0) is None
    other = Store(path)
    assert other.reserve_usage(kid, "d", 1) == 1
    other.close()
    st.close()


class _FailingConn:
    def __init__(self, conn, needle):
        self._conn, self._needle = conn, needle

    def execute(self, sql, *a):
        if self._needle in sql:
            raise RuntimeError("disk on fire")
        return self._conn.execute(sql, *a)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_redeem_rolls_back_seat_when_upgrade_write_fails(tmp_path):
    import pytest

    st = Store(tmp_path / "f.db")
    kid = st.create_key("h", "ex_", "")
    real = st._conn
    st._conn = _FailingConn(real, "UPDATE api_keys")
    with pytest.raises(RuntimeError):
        st.redeem_license(kid, "L", 1)
    st._conn = real
    assert st.license_seats_used("L") == 0
    assert st.get_key("h")["tier"] == "free"
    st.close()


def test_upgrade_requires_auth_and_license(cfg, monkeypatch):
    c = _pro_client(cfg, monkeypatch)
    assert c.post("/v1/upgrade", json={"license_key": "X"}).status_code == 401
    key = c.post("/v1/keys").json()["key"]
    r = c.post("/v1/upgrade", headers=auth(key), json={"license_key": "  "})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"
    r = c.post("/v1/upgrade", headers=auth(key), json={"license_key": 5})
    assert r.status_code == 400


def test_upgrade_gumroad_error_is_502_and_binds_nothing(cfg, monkeypatch):
    import extractly.app as appmod
    from extractly.gumroad import GumroadError

    c = _pro_client(cfg, monkeypatch)

    def boom(*a, **k):
        raise GumroadError("gumroad down")

    monkeypatch.setattr(appmod, "verify_license", boom)
    key = c.post("/v1/keys").json()["key"]
    r = c.post("/v1/upgrade", headers=auth(key), json={"license_key": "LIC"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "verification_error"
    rows = c.store._conn.execute("SELECT COUNT(*) FROM license_seats").fetchone()[0]
    assert rows == 0


def test_kill_switch_refuses_before_reserving(cfg):
    cfg.kill_switch = True
    c = make_client(cfg)
    key = c.post("/v1/keys").json()["key"]
    r = c.post("/v1/extract", headers=auth(key), json={"text": "t", "schema": SCHEMA})
    assert r.status_code == 503
    assert c.get("/v1/usage", headers=auth(key)).json()["used_today"] == 0


def test_parse_networks_accepts_host_bits_and_returns_bool():
    nets = _parse_networks("10.0.0.1/8")
    assert _in_networks("10.9.9.9", nets) is True
    assert _in_networks("garbage", nets) is False
    assert _in_networks("8.8.8.8", nets) is False
