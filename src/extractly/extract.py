"""The extraction engine: schema-guided JSON extraction with honest validation.

Flow per request:
    1. Build a system prompt that pins the caller's JSON Schema.
    2. Call the model (temperature 0). Parse the reply as JSON.
    3. Validate the parsed object against the caller's schema (jsonschema).
    4. If parse or validation fails, retry once with the error fed back.
    5. If it still fails, raise ExtractionFailed: the API returns 422 and
       never returns unvalidated data as if it matched the schema.

Confidence is a documented heuristic, not a model claim:
    1.00  valid on first attempt
    0.80  valid on retry
"""

from __future__ import annotations

import json

import jsonschema

from .llm import LLMError, NebiusClient

SYSTEM_TEMPLATE = """You are a precise data extraction engine. Output ONLY valid JSON, \
no markdown fences, no commentary.

The output MUST conform to this JSON Schema:
{schema}

Rules:
- Include every property defined in the schema. Use null for unknown values \
only if the schema allows it; otherwise use your best extraction or omit \
optional fields.
- Types must match exactly (numbers are JSON numbers, not strings).
- Output a single JSON object, not an array, unless the schema says otherwise."""


class ExtractionFailed(Exception):
    """Raised when the model could not produce schema-valid JSON."""


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _try_once(client: NebiusClient, system: str, user: str, schema: dict):
    content, usage = client.complete(system, user)
    text = _strip_fences(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, usage, f"model output was not valid JSON: {e}"
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        return None, usage, f"output failed schema validation: {e.message}"
    return data, usage, ""


def extract(
    client: NebiusClient, text: str, schema: dict, max_attempts: int = 2
) -> tuple[dict, float, dict]:
    """Returns (data, confidence, usage). Raises ExtractionFailed / LLMError."""
    if not isinstance(schema, dict) or not schema:
        raise ExtractionFailed("schema must be a non-empty JSON Schema object")
    system = SYSTEM_TEMPLATE.format(schema=json.dumps(schema))
    user = f"Extract the fields from the following text:\n\n{text}"
    last_error = ""
    total_prompt = 0
    total_completion = 0
    for attempt in range(max_attempts):
        try:
            data, usage, error = _try_once(client, system, user, schema)
        except LLMError:
            raise
        total_prompt += usage["prompt_tokens"]
        total_completion += usage["completion_tokens"]
        if data is not None:
            confidence = 1.0 if attempt == 0 else 0.8
            return data, confidence, {
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
            }
        last_error = error
        user = (
            f"Your previous output was rejected ({error}). "
            "Fix it and output ONLY valid JSON conforming to the schema.\n\n"
            f"Text:\n\n{text}"
        )
    raise ExtractionFailed(
        f"model could not produce schema-valid JSON after {max_attempts} attempts; "
        f"last error: {last_error}"
    )
