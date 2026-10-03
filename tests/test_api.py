"""End-to-end API tests with a scripted LLM and temp database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient  # noqa: E402

from conftest import FakeLLM  # noqa: E402
from extractly.app import create_app  # noqa: E402
from extractly.db import Store  # noqa: E402

SCHEMA = {
    "type": "object",
    "required": ["vendor", "total"],
    "properties": {"vendor": {"type": "string"}, "total": {"type": "number"}},
}


def make_client(cfg, script=None):
    store = Store(cfg.db_path)
    app = create_app(cfg, store)
    fake = FakeLLM(script or [])
    app.state.llm_factory = lambda: fake
    client = TestClient(app)
    client.fake = fake
    client.store = store
    return client


def auth(key):
    return {"Authorization": f"Bearer {key}"}


def test_healthz(cfg):
    c = make_client(cfg)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_pages_render(cfg):
    c = make_client(cfg)
    for path in ("/", "/pricing", "/docs", "/dashboard"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert "extractly" in r.text.lower()


def test_create_key_and_usage(cfg):
    c = make_client(cfg)
    r = c.post("/v1/keys", json={"label": "t"})
    assert r.status_code == 200
    body = r.json()
    assert body["key"].startswith("ex_live_")
    assert body["tier"] == "free"
    assert body["quota_daily"] == cfg.free_daily_quota
    r2 = c.get("/v1/usage", headers=auth(body["key"]))
    assert r2.status_code == 200
    assert r2.json()["used_today"] == 0


def test_extract_happy_path(cfg):
    c = make_client(cfg, [('{"vendor":"Acme","total":1250}', (100, 40))])
    key = c.post("/v1/keys").json()["key"]
    r = c.post(
        "/v1/extract", headers=auth(key),
        json={"text": "Invoice from Acme for $1,250", "schema": SCHEMA},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"] == {"vendor": "Acme", "total": 1250}
    assert body["confidence"] == 1.0
    assert body["quota"]["used_today"] == 1
    assert c.fake.calls == 1


def test_extract_requires_auth(cfg):
    c = make_client(cfg)
    r = c.post("/v1/extract", json={"text": "x", "schema": SCHEMA})
    assert r.status_code == 401
    r = c.post("/v1/extract", headers=auth("ex_live_bogus"), json={"text": "x", "schema": SCHEMA})
    assert r.status_code == 401


def test_extract_validates_input(cfg):
    c = make_client(cfg)
    key = c.post("/v1/keys").json()["key"]
    h = auth(key)
    assert c.post("/v1/extract", headers=h, json={"text": "", "schema": SCHEMA}).status_code == 400
    assert c.post("/v1/extract", headers=h, json={"text": "x", "schema": {}}).status_code == 400
    assert c.post("/v1/extract", headers=h, json={"text": "x" * 5000, "schema": SCHEMA}).status_code == 400


def test_quota_enforced(cfg):
    c = make_client(cfg, [('{"vendor":"A","total":1}', (10, 5))] * 10)
    key = c.post("/v1/keys").json()["key"]
    h = auth(key)
    for _ in range(cfg.free_daily_quota):
        r = c.post("/v1/extract", headers=h, json={"text": "t", "schema": SCHEMA})
        assert r.status_code == 200
    r = c.post("/v1/extract", headers=h, json={"text": "t", "schema": SCHEMA})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "quota_exceeded"


def test_extraction_failure_is_422_not_fabricated(cfg):
    c = make_client(cfg, [("garbage", (10, 5)), ("garbage", (10, 5))])
    key = c.post("/v1/keys").json()["key"]
    r = c.post("/v1/extract", headers=auth(key), json={"text": "t", "schema": SCHEMA})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "extraction_failed"


def test_upgrade_unconfigured_is_503(cfg):
    c = make_client(cfg)
    key = c.post("/v1/keys").json()["key"]
    r = c.post("/v1/upgrade", headers=auth(key), json={"license_key": "X"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "not_configured"


def test_upgrade_invalid_license_is_402(cfg, monkeypatch):
    import extractly.app as appmod

    cfg.gumroad_product_permalink = "some-product"
    c = make_client(cfg)
    monkeypatch.setattr(appmod, "verify_license", lambda *a, **k: False)
    key = c.post("/v1/keys").json()["key"]
    r = c.post("/v1/upgrade", headers=auth(key), json={"license_key": "BOGUS"})
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "invalid_license"


def test_upgrade_valid_license_sets_pro(cfg, monkeypatch):
    import extractly.app as appmod

    cfg.gumroad_product_permalink = "some-product"
    c = make_client(cfg)
    monkeypatch.setattr(appmod, "verify_license", lambda *a, **k: True)
    key = c.post("/v1/keys").json()["key"]
    r = c.post("/v1/upgrade", headers=auth(key), json={"license_key": "REAL"})
    assert r.status_code == 200
    assert r.json()["tier"] == "pro"
    r2 = c.get("/v1/usage", headers=auth(key))
    assert r2.json()["tier"] == "pro"
    assert r2.json()["quota_daily"] == cfg.pro_daily_quota


def test_key_creation_rate_limit(cfg):
    cfg.key_create_per_hour = 2
    c = make_client(cfg)
    assert c.post("/v1/keys").status_code == 200
    assert c.post("/v1/keys").status_code == 200
    r = c.post("/v1/keys")
    assert r.status_code == 429
