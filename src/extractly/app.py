"""Extractly: unstructured text in, structured JSON out.

Public API (all JSON except the pages):
    POST /v1/keys                 create a free API key (IP rate limited)
    GET  /v1/usage                key usage and quota (Bearer auth)
    POST /v1/extract             run an extraction (Bearer auth)
    POST /v1/upgrade             redeem a Gumroad license for Pro (Bearer auth)
    GET  /healthz                liveness probe

Pages: / (landing), /pricing, /docs, /dashboard
"""

from __future__ import annotations

import hashlib
import ipaddress
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import keys as keylib
from .config import Settings, settings
from .db import Store
from .extract import ExtractionFailed, extract
from .gumroad import GumroadError, verify_license
from .llm import LLMError, NebiusClient

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _err(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _parse_networks(spec: str) -> list:
    nets = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return nets


def _in_networks(ip: str, nets: list) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


def client_ip(request: Request, trusted: list) -> str:
    """Client IP, honouring X-Forwarded-For only from trusted proxies.

    Walks X-Forwarded-For from the right and returns the first hop that is not
    itself a trusted proxy, so a client cannot spoof its address by sending its
    own header.
    """
    peer = request.client.host if request.client else "unknown"
    if not trusted or not _in_networks(peer, trusted):
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
    for hop in reversed([h for h in hops if h]):
        if not _in_networks(hop, trusted):
            return hop
    return peer


def create_app(cfg: Settings | None = None, store: Store | None = None) -> FastAPI:
    cfg = cfg or settings
    app = FastAPI(title="Extractly", version=cfg.version)
    app.state.cfg = cfg
    app.state.store = store or Store(cfg.db_path)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    trusted_proxies = _parse_networks(cfg.trusted_proxies)

    def llm_client() -> NebiusClient:
        factory = getattr(app.state, "llm_factory", None)
        if factory is not None:
            return factory()
        return NebiusClient(
            api_key=cfg.nebius_api_key, base=cfg.nebius_base, model=cfg.model
        )

    def bearer_key(authorization: str | None = Header(default=None)) -> dict:
        st: Store = app.state.store
        if not authorization or not authorization.startswith("Bearer "):
            return None  # type: ignore[return-value]
        return keylib.lookup_key(st, authorization[len("Bearer "):].strip())

    def require_key(rec: dict | None = Depends(bearer_key)):
        if rec is None:
            return None
        return rec

    # -- pages ----------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request):
        return templates.TemplateResponse(request, "landing.html", {"request": request, "cfg": cfg})

    @app.get("/pricing", response_class=HTMLResponse)
    def pricing(request: Request):
        return templates.TemplateResponse(request, "pricing.html", {"request": request, "cfg": cfg})

    @app.get("/docs", response_class=HTMLResponse)
    def docs(request: Request):
        return templates.TemplateResponse(request, "docs.html", {"request": request, "cfg": cfg})

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse(request, "dashboard.html", {"request": request, "cfg": cfg})

    @app.get("/healthz")
    def healthz():
        return {
            "ok": True,
            "version": cfg.version,
            "time": datetime.now(timezone.utc).isoformat(),
        }

    # -- API ------------------------------------------------------------
    @app.post("/v1/keys")
    def create_key(request: Request, body: dict | None = None):
        st: Store = app.state.store
        ip = client_ip(request, trusted_proxies)
        hour_ago = int(time.time()) - 3600
        if st.keys_created_from_ip_since(ip, hour_ago) >= cfg.key_create_per_hour:
            return _err("rate_limited", "too many keys created from this IP", 429)
        label = ""
        if isinstance(body, dict) and isinstance(body.get("label"), str):
            label = body["label"]
        raw, key_id = keylib.issue_key(st, label, ip=ip)
        st.log_request(key_id, "POST /v1/keys", 200)
        return {
            "key": raw,
            "key_id": key_id,
            "tier": "free",
            "quota_daily": cfg.free_daily_quota,
            "note": "This key is shown once. Store it securely.",
        }

    @app.get("/v1/usage")
    def usage(rec: dict | None = Depends(require_key)):
        if rec is None:
            return _err("unauthorized", "valid Bearer API key required", 401)
        st: Store = app.state.store
        quota = cfg.pro_daily_quota if rec["tier"] == "pro" else cfg.free_daily_quota
        used = st.usage_today(rec["id"], _utc_day())
        return {
            "tier": rec["tier"],
            "used_today": used,
            "quota_daily": quota,
            "resets_at": _utc_day() + "T23:59:59Z",
        }

    @app.post("/v1/extract")
    def do_extract(request: Request, body: dict, rec: dict | None = Depends(require_key)):
        st: Store = app.state.store
        if rec is None:
            return _err("unauthorized", "valid Bearer API key required", 401)
        if cfg.kill_switch:
            st.log_request(rec["id"], "POST /v1/extract", 503, error="kill_switch")
            return _err("unavailable", "extractions temporarily paused", 503)
        # per-minute rate limit
        if st.requests_since(rec["id"], int(time.time()) - 60) >= cfg.extract_per_minute:
            st.log_request(rec["id"], "POST /v1/extract", 429, error="rate_limited")
            return _err("rate_limited", "too many requests, slow down", 429)
        quota = cfg.pro_daily_quota if rec["tier"] == "pro" else cfg.free_daily_quota
        text = body.get("text")
        schema = body.get("schema")
        if not isinstance(text, str) or not text.strip():
            return _err("bad_request", "body.text must be a non-empty string", 400)
        if len(text) > cfg.max_text_chars:
            return _err(
                "bad_request",
                f"body.text exceeds {cfg.max_text_chars} characters",
                400,
            )
        if not isinstance(schema, dict) or not schema:
            return _err(
                "bad_request", "body.schema must be a non-empty JSON Schema object", 400
            )
        # daily quota: reserve a unit atomically before the (paid) LLM call so
        # concurrent requests cannot all pass a check-then-increment.
        day = _utc_day()
        used = st.reserve_usage(rec["id"], day, quota)
        if used is None:
            st.log_request(rec["id"], "POST /v1/extract", 429, error="quota_exceeded")
            return _err(
                "quota_exceeded",
                f"daily quota of {quota} extractions reached",
                429,
            )
        started = time.time()
        try:
            data, confidence, usage = extract(llm_client(), text, schema)
        except ExtractionFailed as e:
            st.release_usage(rec["id"], day)
            st.log_request(
                rec["id"],
                "POST /v1/extract",
                422,
                input_chars=len(text),
                latency_ms=int((time.time() - started) * 1000),
                error=str(e)[:200],
            )
            return _err("extraction_failed", str(e), 422)
        except LLMError as e:
            st.release_usage(rec["id"], day)
            st.log_request(
                rec["id"],
                "POST /v1/extract",
                502,
                input_chars=len(text),
                latency_ms=int((time.time() - started) * 1000),
                error=str(e)[:200],
            )
            return _err("model_error", "extraction backend failed; try again later", 502)
        latency_ms = int((time.time() - started) * 1000)
        st.log_request(
            rec["id"],
            "POST /v1/extract",
            200,
            input_chars=len(text),
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            latency_ms=latency_ms,
        )
        return {
            "data": data,
            "confidence": confidence,
            "model": cfg.model,
            "usage": {
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
            },
            "quota": {"used_today": used, "quota_daily": quota},
            "request_id": f"req_{uuid.uuid4().hex[:16]}",
        }

    @app.post("/v1/upgrade")
    def upgrade(body: dict, rec: dict | None = Depends(require_key)):
        st: Store = app.state.store
        if rec is None:
            return _err("unauthorized", "valid Bearer API key required", 401)
        if not cfg.gumroad_product_permalink:
            return _err(
                "not_configured",
                "Pro upgrades are not configured on this server yet",
                503,
            )
        license_key = body.get("license_key") if isinstance(body, dict) else None
        if not isinstance(license_key, str) or not license_key.strip():
            return _err("bad_request", "body.license_key is required", 400)
        try:
            ok = verify_license(cfg.gumroad_product_permalink, license_key.strip())
        except GumroadError as e:
            st.log_request(rec["id"], "POST /v1/upgrade", 502, error=str(e)[:200])
            return _err("verification_error", f"license check failed: {e}", 502)
        if not ok:
            st.log_request(rec["id"], "POST /v1/upgrade", 402, error="invalid_license")
            return _err("invalid_license", "Gumroad did not confirm this license", 402)
        license_hash = hashlib.sha256(license_key.strip().encode("utf-8")).hexdigest()
        if not st.redeem_license(rec["id"], license_hash, cfg.license_seats):
            st.log_request(rec["id"], "POST /v1/upgrade", 409, error="license_in_use")
            return _err(
                "license_in_use",
                "this license has already been used to upgrade the maximum number"
                " of API keys",
                409,
            )
        st.log_request(rec["id"], "POST /v1/upgrade", 200)
        return {"tier": "pro", "quota_daily": cfg.pro_daily_quota}

    return app


app = create_app()
