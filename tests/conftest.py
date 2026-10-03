"""Shared fixtures for the Extractly test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extractly.config import Settings  # noqa: E402
from extractly.db import Store  # noqa: E402


@pytest.fixture()
def cfg(tmp_path):
    s = Settings()
    s.db_path = str(tmp_path / "test.db")
    s.free_daily_quota = 5
    s.pro_daily_quota = 50
    s.key_create_per_hour = 100
    s.extract_per_minute = 100
    s.max_text_chars = 2000
    return s


@pytest.fixture()
def store(cfg):
    st = Store(cfg.db_path)
    yield st
    st.close()


class FakeLLM:
    """Scripted stand-in for NebiusClient. Each script entry is either
    (content, usage) or an exception instance to raise."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        content, usage = item
        return content, {
            "prompt_tokens": usage[0],
            "completion_tokens": usage[1],
            "latency_ms": 5,
        }
