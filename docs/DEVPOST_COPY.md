# Devpost submission copy: Extractly (Galuxium Nexus V2)

## Title
Extractly

## Tagline
Unstructured text in, structured JSON out. A hosted extraction API for automation builders.

## Categories (suggested)
Best Open Source, Monetization

## Description

**The market friction.** Every operations team and indie hacker hits the same wall: the data they need lives in messy text (invoices, emails, support tickets, meeting notes) and their systems need structured JSON. Today that means hand-rolling LLM glue code for every parse step: prompt engineering, output validation, retry logic, API key management, usage metering, abuse controls. It is undifferentiated heavy lifting that every team rebuilds badly.

**What Extractly is.** A hosted structured-extraction API. You POST text plus a JSON Schema; you get back validated data with a confidence score and token usage. One endpoint replaces an entire extraction pipeline.

**Architecture.** FastAPI service on AWS EC2 (t3.micro). Extraction engine: schema-pinned prompts to NVIDIA Nemotron 3 Nano via Nebius Token Factory (temperature 0), JSON parse, `jsonschema` validation, one retry with the error fed back, then an honest 422 if the model cannot comply. Never fabricated output. SQLite (WAL) stores only key hashes, daily counters, and request telemetry (sizes and latencies, never raw text). Abuse controls: API keys, 25/day free quota, 30/min rate limits, 10 keys/hour/IP, 8,000-char input cap, server kill switch. Server-rendered dashboard, docs, and pricing pages; vanilla JS.

**Target cohort.** Automation builders: Zapier/Make/n8n power users, indie hackers shipping AI features, ops teams drowning in unstructured intake. They do not want an ML platform; they want one curl that parses.

**Fiscal architecture.** Free ($0, 25/day) / Pro ($29/mo, 2,000/day) / Team ($99/mo, 20,000/day). Pro is sold as a Gumroad license and redeemed in-app; `/v1/upgrade` verifies the license live against Gumroad. Measured unit cost: $0.000049 per typical extraction ($0.06/1M in, $0.24/1M out, Token Factory catalog pricing). At realistic utilization Pro gross margin is 87%. Full audited math in `docs/MONETIZATION.md` in the repo.

**Built solo** by Fernando Garza for Galuxium Nexus V2. MIT licensed.

## Links
- Production: http://<PUBLIC_IP>:3200  (fill after deploy)
- Repository: https://github.com/fernandogarzaaa/extractly
- Demo video: (YouTube URL after upload)

## Built with
FastAPI, Nebius Token Factory, NVIDIA Nemotron, SQLite, Gumroad, AWS EC2
