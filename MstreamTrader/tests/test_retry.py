"""
Tests pytest : décorateur retry_binance + classification d'erreurs.

Vérifie :
  - Erreurs transitoires (URLError, 5xx, Binance -1003) → retry
  - Erreurs permanentes (400, 401, LOT_SIZE) → remontée immédiate
  - max_attempts respecté
  - backoff exponentiel + jitter respectent l'ordre de grandeur
  - Succès au 2e essai après échec transitoire
"""

import pytest
import sys
import os
import time
import urllib.error
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.retry import retry_binance, _is_retryable_error
from core.exchange import BinanceError


# ─── Classification d'erreurs ─────────────────────────────────────────────────

def test_url_error_is_retryable():
    assert _is_retryable_error(urllib.error.URLError("connection refused"))


def test_timeout_is_retryable():
    assert _is_retryable_error(TimeoutError("timed out"))


def test_connection_error_is_retryable():
    assert _is_retryable_error(ConnectionError("reset"))


def test_http_503_is_retryable():
    exc = urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None)
    assert _is_retryable_error(exc)


def test_http_400_not_retryable():
    exc = urllib.error.HTTPError("u", 400, "Bad Request", {}, None)
    assert _is_retryable_error(exc) is False


def test_http_401_not_retryable():
    exc = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
    assert _is_retryable_error(exc) is False


def test_binance_rate_limit_retryable():
    assert _is_retryable_error(BinanceError("Binance 1003: too many requests"))


def test_binance_lot_size_not_retryable():
    assert _is_retryable_error(BinanceError("LOT_SIZE filter failure")) is False


def test_value_error_not_retryable():
    assert _is_retryable_error(ValueError("foo")) is False


# ─── Décorateur retry_binance ─────────────────────────────────────────────────

def test_succeeds_on_first_try():
    calls = {"n": 0}

    @retry_binance(max_attempts=3, initial_delay=0.01)
    def f():
        calls["n"] += 1
        return "ok"

    assert f() == "ok"
    assert calls["n"] == 1


def test_retries_then_succeeds():
    calls = {"n": 0}

    @retry_binance(max_attempts=3, initial_delay=0.01, jitter=False)
    def f():
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("transient")
        return "ok"

    assert f() == "ok"
    assert calls["n"] == 2


def test_max_attempts_exhausted_raises():
    calls = {"n": 0}

    @retry_binance(max_attempts=3, initial_delay=0.01, jitter=False)
    def f():
        calls["n"] += 1
        raise TimeoutError("always")

    with pytest.raises(TimeoutError):
        f()
    assert calls["n"] == 3


def test_permanent_error_no_retry():
    calls = {"n": 0}

    @retry_binance(max_attempts=5, initial_delay=0.01)
    def f():
        calls["n"] += 1
        raise BinanceError("LOT_SIZE rejected")

    with pytest.raises(BinanceError):
        f()
    assert calls["n"] == 1


def test_backoff_delay_grows():
    """Vérifie que les attentes successives augmentent (backoff exp)."""
    calls = {"n": 0, "ts": []}

    @retry_binance(max_attempts=3, initial_delay=0.05,
                   backoff_factor=2.0, jitter=False)
    def f():
        calls["n"] += 1
        calls["ts"].append(time.time())
        if calls["n"] < 3:
            raise TimeoutError("retry")
        return "ok"

    f()
    # Après 3 essais, on a 3 timestamps
    assert len(calls["ts"]) == 3
    delta_1 = calls["ts"][1] - calls["ts"][0]
    delta_2 = calls["ts"][2] - calls["ts"][1]
    # 1er retry attend ~0.05s, 2e retry attend ~0.10s
    assert delta_1 >= 0.04
    assert delta_2 >= delta_1   # backoff strictement croissant
