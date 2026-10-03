"""Runtime configuration for Extractly. Everything comes from the environment.

Required in production:
    NEBIUS_API_KEY   Token Factory key used for the extraction model.

Optional (sensible defaults for local dev):
    EXTRACTLY_DB_PATH            path to the SQLite file (default: ./extractly.db)
    EXTRACTLY_HOST / PORT        bind address (default: 127.0.0.1:8000)
    EXTRACTLY_MODEL              Nebius model id for extraction
    EXTRACTLY_MAX_TEXT_CHARS     max input text per extraction (default: 8000)
    EXTRACTLY_FREE_DAILY_QUOTA   free tier extractions per day (default: 25)
    EXTRACTLY_PRO_DAILY_QUOTA    pro tier extractions per day (default: 2000)
    EXTRACTLY_KEY_CREATE_PER_HR  max new keys per IP per hour (default: 10)
    EXTRACTLY_EXTRACT_PER_MIN    max extractions per key per minute (default: 30)
    GUMROAD_PRODUCT_PERMALINK    Gumroad product permalink for Pro upgrades
                                 (if unset, /v1/upgrade reports 503 unconfigured)
    EXTRACTLY_KILL_SWITCH        set to "1" to refuse all extractions (abuse brake)
"""

from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Settings:
    db_path: str = os.environ.get("EXTRACTLY_DB_PATH", "./extractly.db")
    host: str = os.environ.get("EXTRACTLY_HOST", "127.0.0.1")
    port: int = _int("EXTRACTLY_PORT", 8000)
    nebius_api_key: str = os.environ.get("NEBIUS_API_KEY", "")
    nebius_base: str = "https://api.tokenfactory.nebius.com/v1"
    model: str = os.environ.get(
        "EXTRACTLY_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    )
    max_text_chars: int = _int("EXTRACTLY_MAX_TEXT_CHARS", 8000)
    free_daily_quota: int = _int("EXTRACTLY_FREE_DAILY_QUOTA", 25)
    pro_daily_quota: int = _int("EXTRACTLY_PRO_DAILY_QUOTA", 2000)
    key_create_per_hour: int = _int("EXTRACTLY_KEY_CREATE_PER_HR", 10)
    extract_per_minute: int = _int("EXTRACTLY_EXTRACT_PER_MIN", 30)
    gumroad_product_permalink: str = os.environ.get("GUMROAD_PRODUCT_PERMALINK", "")
    kill_switch: bool = os.environ.get("EXTRACTLY_KILL_SWITCH", "") == "1"
    version: str = "0.1.0"


settings = Settings()
