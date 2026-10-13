# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- An invalid JSON Schema (e.g. `{"type": "strin"}`) is rejected with 400 before the model is called. It used to be sent to the LLM, then crash `jsonschema` with an unhandled 500, spending tokens and permanently consuming a unit of the daily quota.
- Schemas larger than `EXTRACTLY_MAX_TEXT_CHARS` (as JSON) are rejected with 400; the schema is part of the paid prompt.
- An unexpected error during extraction gives the reserved quota unit back.

### Security
- `/v1/upgrade` now records each redeemed Gumroad license (SHA-256 hash only) against the key it upgraded; one license upgrades at most `EXTRACTLY_LICENSE_SEATS` keys (default 1). Re-redeeming on the same key is idempotent.
- Daily quota is reserved atomically before the LLM call (`UPDATE ... WHERE count < quota`), so concurrent requests can no longer overshoot it. Failed extractions give the unit back.
- Key-creation per-IP limit honours `X-Forwarded-For` only from `EXTRACTLY_TRUSTED_PROXIES`.
- 502 responses no longer echo the backend exception text.
- CI runs `ruff check` (pyflakes + syntax rules, `ruff.toml`).
- Model replies with duplicate JSON keys are rejected (and retried) instead of silently keeping the last value (found by a genesis json-suite probe).

### Added
- CI workflow running pytest on pushes to main and on pull requests.
- Dependabot config for pip and GitHub Actions (weekly).
- requirements-dev.lock with fully pinned transitive dependencies.
- .env.example listing the environment variables Extractly reads.
- SECURITY.md with private reporting contact.
- This changelog.
