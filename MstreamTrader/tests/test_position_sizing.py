"""
Tests pytest : Kelly Criterion + Volatility Targeting.
Vérifie la math du sizing optimal.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.position_sizing import (
    kelly_fraction, fractional_kelly,
    volatility_target_multiplier,
    optimal_position_size,
)


# ─── Kelly Criterion ──────────────────────────────────────────────────────────

def test_kelly_favorable_bet():
    """Win rate 60%, R/R 2:1 → Kelly > 0."""
    f = kelly_fraction(win_rate=0.60, avg_win=20, avg_loss=10)
    # b = 2, p = 0.6, q = 0.4 → f = (0.6*2 - 0.4)/2 = 0.4
    assert abs(f - 0.40) < 0.001


def test_kelly_unfavorable_bet_returns_zero():
    """Win rate 30%, R/R 1:1 → EV négative → Kelly = 0."""
    f = kelly_fraction(win_rate=0.30, avg_win=10, avg_loss=10)
    assert f == 0.0


def test_kelly_edge_cases():
    """Win rate 0 ou 1 → Kelly = 0."""
    assert kelly_fraction(win_rate=0.0, avg_win=10, avg_loss=10) == 0.0
    assert kelly_fraction(win_rate=1.0, avg_win=10, avg_loss=10) == 0.0
    assert kelly_fraction(win_rate=0.5, avg_win=10, avg_loss=0) == 0.0


def test_fractional_kelly_scales_correctly():
    """Fractional Kelly = fraction × full_kelly."""
    full = kelly_fraction(0.60, 20, 10)
    quarter = fractional_kelly(0.60, 20, 10, fraction=0.25)
    assert abs(quarter - (full * 0.25)) < 1e-9


# ─── Volatility targeting ────────────────────────────────────────────────────

def test_vol_target_high_vol_reduces_size():
    """Marché volatile (4%) vs target (2%) → multiplier < 1."""
    m = volatility_target_multiplier(realized_vol_pct=4.0, target_vol_pct=2.0)
    assert m == 0.5


def test_vol_target_low_vol_increases_size():
    """Marché calme (1%) vs target (2%) → multiplier > 1."""
    m = volatility_target_multiplier(realized_vol_pct=1.0, target_vol_pct=2.0)
    assert m == 2.0


def test_vol_target_clamping():
    """Multiplier est borné [0.25, 2.0] par défaut."""
    # Cas extrêmes
    m_high = volatility_target_multiplier(realized_vol_pct=0.1, target_vol_pct=2.0)
    assert m_high <= 2.0
    m_low = volatility_target_multiplier(realized_vol_pct=20.0, target_vol_pct=2.0)
    assert m_low >= 0.25


# ─── Optimal position size ────────────────────────────────────────────────────

def test_optimal_size_respects_max_risk():
    """Si SL proche, max_risk borne la taille."""
    r = optimal_position_size(
        capital=1000, win_rate=0.55, avg_win=20, avg_loss=10,
        entry_price=100, stop_loss=99,   # SL à 1 % → très proche
        realized_vol_pct=2.0,
        max_risk_per_trade=2.0, max_position_pct=80.0,
        kelly_fraction_used=0.25,
    )
    # Risk réel ne doit pas dépasser 2 % du capital
    assert r["risk_pct"] <= 2.1   # petite tolérance float


def test_optimal_size_invalid_sl_returns_zero():
    """SL au-dessus du prix (invalide pour un long)."""
    r = optimal_position_size(
        capital=1000, win_rate=0.55, avg_win=20, avg_loss=10,
        entry_price=100, stop_loss=110,   # SL > entry → bug
        realized_vol_pct=2.0,
    )
    assert r["size_usdt"] == 0
    assert r["binding"] == "invalid_sl"


def test_optimal_size_below_min_notional_returns_zero():
    """Si la taille optimale < 10 USDT (min Binance), retourne 0."""
    r = optimal_position_size(
        capital=100, win_rate=0.55, avg_win=20, avg_loss=10,
        entry_price=100, stop_loss=99,
        realized_vol_pct=2.0,
        max_risk_per_trade=0.5,   # 0.5 % de 100 = 0.5 USDT → trop petit
        min_position_usdt=10.0,
    )
    assert r["size_usdt"] == 0
    assert r["binding"] == "min_notional"
