"""Minimal Token Factory chat-completions client (stdlib only).

Used by the extraction engine. Raises LLMError on any failure so callers
can translate it into a 502 without ever fabricating extraction output.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


class NebiusClient:
    def __init__(
        self,
        api_key: str,
        base: str = "https://api.tokenfactory.nebius.com/v1",
        model: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        timeout: int = 90,
    ) -> None:
        self.api_key = api_key
        self.base = base.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        """Returns (content, usage_dict). Raises LLMError on failure."""
        if not self.api_key:
            raise LLMError("NEBIUS_API_KEY is not configured on the server")
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(
            self.base + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise LLMError(f"Token Factory HTTP {e.code}") from e
        except Exception as e:  # timeouts, DNS, connection resets
            raise LLMError(f"Token Factory request failed: {type(e).__name__}") from e
        latency_ms = int((time.time() - started) * 1000)
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise LLMError("Token Factory returned non-JSON") from e
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("Token Factory response had no choices")
        content = (choices[0].get("message") or {}).get("content")
        if not content or not content.strip():
            raise LLMError("Token Factory returned empty content")
        usage = data.get("usage") or {}
        return content, {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "latency_ms": latency_ms,
        }
