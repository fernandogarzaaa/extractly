"""Gumroad license verification for Pro upgrades.

POST https://api.gumroad.com/v2/licenses/verify
  {product_permalink, license_key} -> {success: bool, ...}

A Pro upgrade is only granted when Gumroad itself confirms the license.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class GumroadError(Exception):
    pass


def verify_license(product_permalink: str, license_key: str, timeout: int = 30) -> bool:
    """Returns True iff Gumroad confirms the license. Raises GumroadError on
    transport failure; returns False for invalid/unknown licenses."""
    payload = {
        "product_permalink": product_permalink,
        "license_key": license_key,
    }
    req = urllib.request.Request(
        "https://api.gumroad.com/v2/licenses/verify",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Gumroad returns 404/410 for unknown products or revoked keys:
        # that is a "not licensed" answer, not a transport failure.
        if e.code in (404, 410):
            return False
        raise GumroadError(f"Gumroad HTTP {e.code}") from e
    except Exception as e:
        raise GumroadError(f"Gumroad request failed: {type(e).__name__}") from e
    return bool(data.get("success"))
