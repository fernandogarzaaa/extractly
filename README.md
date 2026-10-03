# Extractly

Unstructured text in, structured JSON out. A hosted extraction API for automation builders.

Send messy text and a JSON Schema, get back validated data with confidence scores and token usage. Built for [Galuxium Nexus V2](https://galuxium-nexus-v2-29411.devpost.com/).

## What it does

```bash
curl -X POST https://YOUR-HOST/v1/extract \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ex_live_...' \
  -d '{"text":"Invoice from Acme Corp dated 2026-09-15 for $1,250.00",
       "schema":{"type":"object","required":["vendor","date","total"],
                 "properties":{"vendor":{"type":"string"},
                               "date":{"type":"string"},
                               "total":{"type":"number"}}}}'
```

```json
{"data":{"vendor":"Acme Corp","date":"2026-09-15","total":1250},
 "confidence":1.0,
 "model":"nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
 "usage":{"prompt_tokens":207,"completion_tokens":151},
 "quota":{"used_today":3,"quota_daily":25},
 "request_id":"req_1791015000000"}
```

Every response is validated against your schema before it leaves the server. If the model cannot produce schema-valid JSON after a retry, you get `422 extraction_failed`, never fabricated data.

## Architecture

```
                   +------------------+
                   |  Jinja2 pages    |  /  /pricing  /docs  /dashboard
                   |  (landing, docs) |
                   +--------+---------+
                            |
+------------------+  +-----v------+  +------------------+
| POST /v1/keys    |  |  FastAPI   |  | POST /v1/upgrade |
| GET  /v1/usage   +->+  routes    +-<+  (Gumroad verify) |
| POST /v1/extract |  +-----+------+  +------------------+
+------------------+        |
                     +-----v------+
                     |  extract   |  prompt -> model -> parse ->
                     |  engine    |  validate -> retry once ->
                     +-----+------+  422 on persistent failure
                           |
              +------------v-------------+
              | Nebius Token Factory     |
              | nvidia/NVIDIA-Nemotron-  |
              | 3-Nano-30B-A3B           |
              +--------------------------+
```

**Request lifecycle** (`POST /v1/extract`):
1. Bearer key lookup (SHA-256 hash only, constant-time compare semantics via hash equality).
2. Kill-switch check, per-minute rate limit, daily quota check.
3. Extraction engine: schema-pinned prompt, temperature 0, JSON parse, `jsonschema` validation, one retry with the error fed back.
4. Usage counter increment, request logged (sizes and latencies only; raw text and reasoning traces are never persisted).

**Abuse controls:** API keys required, 25/day free quota, 30/min/key rate limit, 10 keys/hour/IP, 8,000-char input cap, server kill switch (`EXTRACTLY_KILL_SWITCH=1`).

## Tech stack

| Layer | Choice |
|---|---|
| API | FastAPI + Uvicorn |
| Pages | Jinja2 server-rendered, vanilla JS, hand-written CSS |
| Extraction model | NVIDIA Nemotron 3 Nano via Nebius Token Factory |
| Validation | `jsonschema` (Draft 2020-12) |
| HTTP (outbound) | stdlib `urllib` (LLM, Gumroad) |
| Database | SQLite (WAL mode) |
| Billing | Gumroad license verification (Pro upgrades) |
| Deploy | systemd + pull-based auto-update on AWS EC2 (t3.micro) |

## Database schema

```sql
api_keys(id, key_hash UNIQUE, key_prefix, label, tier, revoked, created_at)
usage_daily(key_id, day, count)                 -- PRIMARY KEY (key_id, day)
requests(id, key_id, ts, endpoint, status, input_chars,
         prompt_tokens, completion_tokens, latency_ms, error)
key_events(id, key_id, ts, event, detail, ip)   -- created | upgraded | revoked
```

Only key hashes are stored; raw keys are shown once at creation. Request logs keep sizes and latencies, never raw text. Migration path to Postgres is 1:1 (same tables, `SERIAL` keys).

## Local development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
export NEBIUS_API_KEY=...        # Token Factory key (extraction backend)
.venv/bin/python -m pytest tests/ -q
EXTRACTLY_HOST=127.0.0.1 EXTRACTLY_PORT=8000 .venv/bin/python -m extractly
```

Open http://127.0.0.1:8000. Without `NEBIUS_API_KEY`, pages and key management work; `/v1/extract` returns `502 model_error` until the key is configured.

## Configuration

See `src/extractly/config.py` for the full list. The knobs that matter:

| Variable | Default | Purpose |
|---|---|---|
| `NEBIUS_API_KEY` | (empty) | Token Factory key for extraction |
| `EXTRACTLY_DB_PATH` | `./extractly.db` | SQLite file |
| `EXTRACTLY_MODEL` | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Extraction model |
| `EXTRACTLY_FREE_DAILY_QUOTA` | `25` | Free extractions/day |
| `EXTRACTLY_PRO_DAILY_QUOTA` | `2000` | Pro extractions/day |
| `GUMROAD_PRODUCT_PERMALINK` | (empty) | Enables `/v1/upgrade` when set |
| `EXTRACTLY_KILL_SWITCH` | (empty) | Set `1` to pause extractions |

## Monetization

Free / $29/mo Pro / $99/mo Team. Pro is sold as a Gumroad license and redeemed via `/v1/upgrade`, which verifies the license live against Gumroad. Full unit economics in [`docs/MONETIZATION.md`](docs/MONETIZATION.md).

## License

MIT. See [LICENSE](LICENSE).
