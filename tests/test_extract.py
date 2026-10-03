"""Tests for the extraction engine with a scripted LLM."""

import pytest

from conftest import FakeLLM
from extractly.extract import ExtractionFailed, extract
from extractly.llm import LLMError

SCHEMA = {
    "type": "object",
    "required": ["vendor", "total"],
    "properties": {"vendor": {"type": "string"}, "total": {"type": "number"}},
}


def test_valid_first_try_confidence_one():
    llm = FakeLLM([('{"vendor":"Acme","total":1250}', (50, 20))])
    data, conf, usage = extract(llm, "invoice from Acme for $1250", SCHEMA)
    assert data == {"vendor": "Acme", "total": 1250}
    assert conf == 1.0
    assert usage["prompt_tokens"] == 50
    assert llm.calls == 1


def test_retry_then_valid_confidence_lower():
    llm = FakeLLM(
        [
            ("not json at all", (50, 10)),
            ('{"vendor":"Acme","total":1250}', (60, 20)),
        ]
    )
    data, conf, usage = extract(llm, "invoice from Acme for $1250", SCHEMA)
    assert data["vendor"] == "Acme"
    assert conf == 0.8
    assert llm.calls == 2
    assert usage["prompt_tokens"] == 110


def test_schema_violation_retried():
    llm = FakeLLM(
        [
            ('{"vendor":"Acme","total":"lots"}', (50, 20)),  # total must be number
            ('{"vendor":"Acme","total":1250}', (60, 20)),
        ]
    )
    data, conf, _ = extract(llm, "text", SCHEMA)
    assert data["total"] == 1250
    assert conf == 0.8


def test_persistent_failure_raises():
    llm = FakeLLM([("garbage", (10, 5)), ("still garbage", (10, 5))])
    with pytest.raises(ExtractionFailed):
        extract(llm, "text", SCHEMA)
    assert llm.calls == 2


def test_llm_error_propagates():
    llm = FakeLLM([LLMError("boom")])
    with pytest.raises(LLMError):
        extract(llm, "text", SCHEMA)


def test_empty_schema_rejected():
    llm = FakeLLM([])
    with pytest.raises(ExtractionFailed):
        extract(llm, "text", {})


def test_markdown_fences_stripped():
    llm = FakeLLM([('```json\n{"vendor":"Acme","total":9}\n```', (50, 20))])
    data, conf, _ = extract(llm, "text", SCHEMA)
    assert data == {"vendor": "Acme", "total": 9}
    assert conf == 1.0
