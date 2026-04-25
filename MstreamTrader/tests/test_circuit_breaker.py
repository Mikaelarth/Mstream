"""
Tests pytest : Circuit Breaker — state machine + auto-recovery + thread-safety.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.circuit_breaker import (
    CircuitBreaker, CircuitConfig, CircuitState,
)


def test_initial_state_is_healthy():
    cb = CircuitBreaker()
    assert cb.get_state() == CircuitState.HEALTHY
    assert cb.can_open_new_positions()
    assert cb.can_manage_exits()


def test_consecutive_sl_triggers():
    """5 SL consécutifs → TRIGGERED, entrées bloquées."""
    cb = CircuitBreaker(CircuitConfig(max_consecutive_sl=5))
    for _ in range(5):
        cb.report_trade_result(pnl=-10, exit_reason="EXIT_SL")
    assert cb.get_state() == CircuitState.TRIGGERED
    assert not cb.can_open_new_positions()
    assert cb.can_manage_exits()   # exits toujours autorisés


def test_winning_trade_resets_consecutive_sl():
    """Un trade gagnant remet consecutive_sl à 0."""
    cb = CircuitBreaker(CircuitConfig(max_consecutive_sl=5))
    for _ in range(3):
        cb.report_trade_result(pnl=-10, exit_reason="EXIT_SL")
    # Reset après win
    cb.report_trade_result(pnl=+20, exit_reason="EXIT_TP")
    for _ in range(3):
        cb.report_trade_result(pnl=-10, exit_reason="EXIT_SL")
    # Seulement 3 SL consécutifs après le TP, pas encore TRIGGERED
    assert cb.get_state() == CircuitState.HEALTHY


def test_drawdown_triggers():
    """DD > 20 % → TRIGGERED."""
    cb = CircuitBreaker(CircuitConfig(total_drawdown_pct=20.0))
    cb.report_capital(1000.0)   # peak = 1000
    cb.report_capital(799.0)    # DD = 20.1 %
    assert cb.get_state() == CircuitState.TRIGGERED


def test_api_errors_freeze():
    """5 erreurs API consécutives → FROZEN."""
    cb = CircuitBreaker(CircuitConfig(max_api_errors_consecutive=5))
    for _ in range(5):
        cb.report_api_error("test")
    assert cb.get_state() == CircuitState.FROZEN
    assert not cb.can_manage_exits()


def test_api_success_resets_errors():
    """report_api_success remet consecutive_api_errors à 0."""
    cb = CircuitBreaker(CircuitConfig(max_api_errors_consecutive=5))
    for _ in range(3):
        cb.report_api_error("test")
    cb.report_api_success()
    for _ in range(3):
        cb.report_api_error("test")
    assert cb.get_state() == CircuitState.HEALTHY   # seulement 3 après reset


def test_manual_reset_resets_peak_capital():
    """manual_reset doit reset peak_capital (fix bug audit #4)."""
    cb = CircuitBreaker()
    cb.report_capital(2000.0)
    assert cb.state.peak_capital == 2000.0
    cb.manual_reset()
    assert cb.state.peak_capital == 0.0
    assert cb.state.rapid_check_samples == []


def test_get_state_snapshot_atomic():
    """get_state_snapshot retourne toutes les clés attendues."""
    cb = CircuitBreaker()
    cb.report_trade_result(pnl=-10, exit_reason="EXIT_SL")
    snap = cb.get_state_snapshot()
    assert "state" in snap
    assert "consecutive_sl" in snap
    assert "peak_capital" in snap
    assert snap["consecutive_sl"] == 1


def test_elevation_monotonic():
    """L'état ne peut que monter (HEALTHY→WARNING→TRIGGERED), jamais descendre via _elevate."""
    cb = CircuitBreaker(CircuitConfig(max_api_errors_consecutive=3))
    for _ in range(3):
        cb.report_api_error("test")
    # Maintenant FROZEN
    assert cb.get_state() == CircuitState.FROZEN
    # Un anomaly (warning) ne redescend PAS de FROZEN
    cb.report_anomaly("TEST", "fake")
    assert cb.get_state() == CircuitState.FROZEN
