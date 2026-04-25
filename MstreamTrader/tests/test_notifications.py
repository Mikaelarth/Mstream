"""
Tests pytest : module notifications Telegram.

On ne fait JAMAIS de vrai appel HTTP. Tous les tests :
  - mockent _send_telegram_sync
  - vérifient que la couche logique appelle correctement
  - vérifient le rate limiting
  - vérifient is_configured / set_credentials / clear_credentials

Ces tests garantissent qu'un changement dans les helpers (notify_entry, etc.)
ne casse pas l'envoi sans que personne ne le remarque.
"""

import pytest
import sys
import os
import time
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import notifications, database


@pytest.fixture(autouse=True)
def clean_creds():
    """Reset des credentials avant/après chaque test."""
    database.init_db()
    notifications.clear_credentials()
    yield
    notifications.clear_credentials()


# ─── Configuration ────────────────────────────────────────────────────────────

def test_not_configured_by_default():
    assert notifications.is_configured() is False


def test_set_credentials_marks_configured():
    notifications.set_credentials("123:abc", "456789")
    assert notifications.is_configured() is True


def test_clear_credentials():
    notifications.set_credentials("123:abc", "456789")
    notifications.clear_credentials()
    assert notifications.is_configured() is False


def test_credentials_stored_encrypted():
    """Le token brut ne doit PAS apparaître en clair en DB."""
    notifications.set_credentials("super_secret_token_xyz", "9999")
    raw = database.get_setting("telegram_bot_token")
    # Soit préfixe enc:, soit absent (pas le token brut)
    assert raw != "super_secret_token_xyz"


# ─── Send sync (mock) ─────────────────────────────────────────────────────────

def test_send_sync_returns_false_if_not_configured():
    ok = notifications._send_telegram_sync("hello")
    assert ok is False


def test_send_sync_calls_urllib_when_configured(monkeypatch):
    """Vérifie que la requête HTTP est bien construite."""
    notifications.set_credentials("token123", "chat99")

    captured = {"url": None, "data": None}

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"ok": true}'

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return FakeResponse()

    monkeypatch.setattr(notifications.urllib.request, "urlopen", fake_urlopen)
    ok = notifications._send_telegram_sync("hello world")
    assert ok is True
    assert captured["url"] is not None
    assert "token123" in captured["url"]
    assert "sendMessage" in captured["url"]
    assert b"chat99" in captured["data"]
    assert b"hello+world" in captured["data"] or b"hello%20world" in captured["data"]


def test_send_sync_handles_network_error(monkeypatch):
    notifications.set_credentials("t", "c")
    import urllib.error

    def fake_urlopen(*a, **kw):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(notifications.urllib.request, "urlopen", fake_urlopen)
    ok = notifications._send_telegram_sync("msg")
    assert ok is False


def test_send_sync_handles_telegram_error_response(monkeypatch):
    """Si Telegram répond {ok: false}, on retourne False."""
    notifications.set_credentials("t", "c")

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"ok": false, "description": "Bad token"}'

    monkeypatch.setattr(
        notifications.urllib.request, "urlopen",
        lambda *a, **kw: FakeResponse()
    )
    ok = notifications._send_telegram_sync("msg")
    assert ok is False


# ─── Rate limiting ────────────────────────────────────────────────────────────

def test_rate_limit_enforced(monkeypatch):
    """Deux appels rapprochés doivent être espacés d'au moins _MIN_INTERVAL."""
    notifications.set_credentials("t", "c")

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"ok": true}'

    monkeypatch.setattr(
        notifications.urllib.request, "urlopen",
        lambda *a, **kw: FakeResponse()
    )

    # Reset rate limiter timer pour le test
    notifications._last_send_ts = 0.0

    t0 = time.time()
    notifications._send_telegram_sync("msg1")
    notifications._send_telegram_sync("msg2")
    elapsed = time.time() - t0
    # 2e envoi doit attendre _MIN_INTERVAL_BETWEEN_MSG (0.5s)
    assert elapsed >= notifications._MIN_INTERVAL_BETWEEN_MSG * 0.9


# ─── Async send ───────────────────────────────────────────────────────────────

def test_send_async_no_op_if_not_configured(monkeypatch):
    """Sans config, send_async ne lance pas de thread."""
    started = {"flag": False}

    class FakeThread:
        def __init__(self, *a, **kw): started["flag"] = True
        def start(self): pass

    monkeypatch.setattr(notifications.threading, "Thread", FakeThread)
    notifications.send_async("hello")
    assert started["flag"] is False


def test_send_async_starts_thread_when_configured(monkeypatch):
    notifications.set_credentials("t", "c")
    started = {"flag": False}

    real_thread = threading.Thread

    def spy_thread(*a, **kw):
        started["flag"] = True
        # On passe un target inerte pour ne pas appeler urlopen
        kw.pop("args", None)
        kw["target"] = lambda: None
        return real_thread(**kw)

    monkeypatch.setattr(notifications.threading, "Thread", spy_thread)
    notifications.send_async("hello")
    assert started["flag"] is True


# ─── Helpers de message ───────────────────────────────────────────────────────

def test_notify_entry_calls_send_async(monkeypatch):
    captured = {"text": None}

    def fake_send_async(text, silent=False):
        captured["text"] = text

    monkeypatch.setattr(notifications, "send_async", fake_send_async)
    notifications.notify_entry(
        coin_id="bitcoin", symbol="BTC", entry_price=50000.0,
        quantity=0.001, amount_usdt=50.0, sl=49000.0, tp=52000.0,
        regime="bull", profile="aggressive",
    )
    assert captured["text"] is not None
    assert "BTC" in captured["text"]
    assert "ENTRY" in captured["text"]
    assert "BULL" in captured["text"]
    assert "aggressive" in captured["text"]


def test_notify_exit_includes_pnl_and_r(monkeypatch):
    captured = {"text": None}
    monkeypatch.setattr(
        notifications, "send_async",
        lambda text, silent=False: captured.update(text=text)
    )
    notifications.notify_exit(
        coin_id="eth", symbol="ETH", entry_price=2000.0, exit_price=2100.0,
        pnl=10.0, r_multiple=1.5, reason="EXIT_TP",
    )
    assert "ETH" in captured["text"]
    assert "+10.00" in captured["text"] or "10.00" in captured["text"]
    assert "1.50R" in captured["text"] or "+1.50R" in captured["text"]


def test_notify_circuit_breaker_includes_state(monkeypatch):
    captured = {"text": None}
    monkeypatch.setattr(
        notifications, "send_async",
        lambda text, silent=False: captured.update(text=text)
    )
    notifications.notify_circuit_breaker("TRIGGERED", "5 SL consécutifs")
    assert "TRIGGERED" in captured["text"]
    assert "5 SL" in captured["text"]
