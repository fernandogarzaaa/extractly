"""Gumroad license verification tests.

The unit tests mock transport. One live negative test hits the real
Gumroad API with a bogus license and expects False; it skips gracefully
if the network is unavailable.
"""

import urllib.error

import pytest

from extractly import gumroad


def test_verify_false_on_404(monkeypatch):
    def fake_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(gumroad.urllib.request, "urlopen", fake_urlopen)
    assert gumroad.verify_license("nope-product", "nope-key") is False


def test_verify_true_on_success(monkeypatch):
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"success": true}'

    monkeypatch.setattr(gumroad.urllib.request, "urlopen", lambda req, timeout=30: Resp())
    assert gumroad.verify_license("prod", "key") is True


def test_verify_raises_on_transport_error(monkeypatch):
    def fake_urlopen(req, timeout=30):
        raise TimeoutError("down")

    monkeypatch.setattr(gumroad.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(gumroad.GumroadError):
        gumroad.verify_license("prod", "key")


def test_live_negative_against_real_gumroad():
    """Bogus license against the real API must come back False (or skip)."""
    try:
        ok = gumroad.verify_license(
            "definitely-not-a-real-product-xyz", "definitely-bogus-key", timeout=20
        )
    except gumroad.GumroadError as e:
        pytest.skip(f"network unavailable for live check: {e}")
    assert ok is False
