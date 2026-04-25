"""
Tests pytest : métriques de performance (Sharpe/Sortino/Calmar/PF/etc.).

Pure math sur des séries de retours connus. Toute valeur publiée par le
backtest dépend de ces fonctions — un bug ici fausse toutes les analyses.

Stratégie :
  - Cas dégénérés (listes vides, série trop courte) → 0.0 sans crash
  - Cas connus (gains constants, returns deterministes) → valeurs prédictibles
  - Bornes (max DD ≥ 0, profit_factor ≥ 0, win_rate ∈ [0, 100])
  - Cohérence (full report : tous les champs présents et arrondis)
"""

import math
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.metrics import (
    total_return_pct, annualized_return_pct, period_returns,
    max_drawdown_pct, drawdown_duration_candles,
    sharpe_ratio, sortino_ratio, calmar_ratio,
    win_rate_pct, profit_factor, expectancy, avg_win_loss,
    r_multiple_stats, compute_full_report,
)


# ─── Returns ──────────────────────────────────────────────────────────────────

def test_total_return_pct_basic():
    assert total_return_pct(1000, 1100) == pytest.approx(10.0)
    assert total_return_pct(1000, 900) == pytest.approx(-10.0)


def test_total_return_pct_invalid_initial():
    assert total_return_pct(0, 100) == 0.0
    assert total_return_pct(-50, 100) == 0.0


def test_annualized_return_doubling_in_a_year():
    """Capital doublé sur 365 jours → CAGR = 100%."""
    res = annualized_return_pct(1000, 2000, 365)
    assert res == pytest.approx(100.0)


def test_annualized_return_invalid_inputs():
    assert annualized_return_pct(0, 100, 30) == 0.0
    assert annualized_return_pct(100, 100, 0) == 0.0
    assert annualized_return_pct(100, -50, 30) == -100.0


def test_period_returns_basic():
    eq = [100, 110, 121]   # +10%, +10%
    out = period_returns(eq)
    assert len(out) == 2
    assert out[0] == pytest.approx(0.10)
    assert out[1] == pytest.approx(0.10)


def test_period_returns_too_short():
    assert period_returns([100]) == []
    assert period_returns([]) == []


# ─── Drawdown ─────────────────────────────────────────────────────────────────

def test_max_drawdown_no_drawdown():
    """Courbe strictement croissante → DD = 0."""
    eq = [100, 110, 120, 130]
    assert max_drawdown_pct(eq) == 0.0


def test_max_drawdown_known_value():
    """Peak 200, trough 150 → DD = 25%."""
    eq = [100, 200, 150, 180]
    assert max_drawdown_pct(eq) == pytest.approx(25.0)


def test_max_drawdown_empty():
    assert max_drawdown_pct([]) == 0.0


def test_max_drawdown_returns_positive():
    """Toujours retourne valeur positive (pourcentage)."""
    eq = [100, 50, 25, 10]
    assert max_drawdown_pct(eq) >= 0


def test_drawdown_duration_basic():
    """Mesure peak-to-trough : descend pendant 3 bougies avant recovery.

    Note : convention 'temps passé sous le peak avant la 1re bougie de
    récupération'. Une autre convention (peak-to-peak) donnerait 4.
    """
    eq = [100, 90, 80, 70, 100]
    assert drawdown_duration_candles(eq) == 3


def test_drawdown_duration_no_drawdown():
    eq = [100, 110, 120]
    assert drawdown_duration_candles(eq) == 0


# ─── Sharpe / Sortino / Calmar ────────────────────────────────────────────────

def test_sharpe_constant_returns_zero():
    """Variance nulle → Sharpe = 0 (par convention, division par 0)."""
    assert sharpe_ratio([0.01] * 10) == 0.0


def test_sharpe_positive_for_positive_mean():
    """Returns positifs avec variance modérée → Sharpe > 0."""
    returns = [0.01, 0.02, 0.005, 0.015, 0.01]
    s = sharpe_ratio(returns, periods_per_year=252)
    assert s > 0


def test_sharpe_too_short():
    assert sharpe_ratio([]) == 0.0
    assert sharpe_ratio([0.01]) == 0.0


def test_sortino_no_downside_returns_inf_or_zero():
    """Aucun retour négatif → infini si excess > 0, sinon 0."""
    out = sortino_ratio([0.01, 0.02, 0.03])
    assert out == float("inf")


def test_sortino_with_downside_returns_finite():
    returns = [0.02, -0.01, 0.015, -0.005, 0.01]
    s = sortino_ratio(returns)
    assert math.isfinite(s)


def test_sortino_too_short():
    assert sortino_ratio([]) == 0.0
    assert sortino_ratio([0.01]) == 0.0


def test_calmar_basic():
    """20% / 10% = 2.0."""
    assert calmar_ratio(20.0, 10.0) == pytest.approx(2.0)


def test_calmar_zero_drawdown():
    """DD = 0 et return positif → infini."""
    assert calmar_ratio(15.0, 0.0) == float("inf")
    assert calmar_ratio(-5.0, 0.0) == 0.0


# ─── Win rate / Profit factor / Expectancy ───────────────────────────────────

def test_win_rate_basic():
    trades = [{"pnl": 10}, {"pnl": -5}, {"pnl": 20}, {"pnl": -3}]
    assert win_rate_pct(trades) == pytest.approx(50.0)


def test_win_rate_empty():
    assert win_rate_pct([]) == 0.0


def test_win_rate_ignores_trades_without_pnl():
    """Trades sans clé 'pnl' sont exclus."""
    trades = [{"pnl": 10}, {"side": "BUY"}, {"pnl": -5}]
    assert win_rate_pct(trades) == pytest.approx(50.0)


def test_profit_factor_basic():
    """gains 30, losses 10 → PF = 3.0."""
    trades = [{"pnl": 20}, {"pnl": 10}, {"pnl": -5}, {"pnl": -5}]
    assert profit_factor(trades) == pytest.approx(3.0)


def test_profit_factor_no_losses_returns_inf():
    trades = [{"pnl": 10}, {"pnl": 5}]
    assert profit_factor(trades) == float("inf")


def test_profit_factor_no_gains_zero():
    trades = [{"pnl": -10}, {"pnl": -5}]
    assert profit_factor(trades) == 0.0


def test_expectancy_basic():
    trades = [{"pnl": 10}, {"pnl": -5}, {"pnl": 20}, {"pnl": -5}]
    # (10 - 5 + 20 - 5) / 4 = 5
    assert expectancy(trades) == pytest.approx(5.0)


def test_expectancy_empty():
    assert expectancy([]) == 0.0


def test_avg_win_loss():
    trades = [{"pnl": 10}, {"pnl": 30}, {"pnl": -5}, {"pnl": -15}]
    avg_w, avg_l = avg_win_loss(trades)
    assert avg_w == pytest.approx(20.0)
    assert avg_l == pytest.approx(10.0)
    # Loss retournée en positif


# ─── R-multiples ──────────────────────────────────────────────────────────────

def test_r_stats_basic():
    trades = [{"r_multiple": 1.0}, {"r_multiple": -1.0},
              {"r_multiple": 2.5}, {"r_multiple": 0.5}]
    s = r_multiple_stats(trades)
    assert s["count"] == 4
    assert s["avg"] == pytest.approx(0.75)
    assert s["best"] == 2.5
    assert s["worst"] == -1.0


def test_r_stats_median_odd():
    trades = [{"r_multiple": 1}, {"r_multiple": 3}, {"r_multiple": 5}]
    s = r_multiple_stats(trades)
    assert s["median"] == 3


def test_r_stats_median_even():
    trades = [{"r_multiple": 1}, {"r_multiple": 2},
              {"r_multiple": 3}, {"r_multiple": 4}]
    s = r_multiple_stats(trades)
    assert s["median"] == pytest.approx(2.5)


def test_r_stats_empty():
    s = r_multiple_stats([])
    assert s["count"] == 0
    assert s["avg"] == 0.0


def test_r_stats_filters_none():
    """Trades sans r_multiple sont ignorés."""
    trades = [{"r_multiple": 2}, {"pnl": 10}, {"r_multiple": None}]
    s = r_multiple_stats(trades)
    assert s["count"] == 1


# ─── Full report ──────────────────────────────────────────────────────────────

def test_compute_full_report_shape():
    trades = [
        {"pnl": 50, "r_multiple": 1.5},
        {"pnl": -20, "r_multiple": -1.0},
        {"pnl": 30, "r_multiple": 0.8},
    ]
    eq = [1000, 1050, 1030, 1060]
    report = compute_full_report(
        trades=trades, equity_curve=eq,
        initial_capital=1000.0, final_capital=1060.0,
        duration_days=30, periods_per_year=8760,
    )
    expected = {
        "initial_capital", "final_capital", "total_return_pct",
        "annualized_return", "max_drawdown_pct", "max_dd_duration",
        "sharpe", "sortino", "calmar",
        "total_trades", "winners", "losers", "win_rate_pct",
        "profit_factor", "expectancy_usdt",
        "avg_win_usdt", "avg_loss_usdt", "best_trade_usdt", "worst_trade_usdt",
        "r_avg", "r_median", "r_best", "r_worst",
    }
    assert expected.issubset(report.keys())
    # Cohérence des compteurs
    assert report["total_trades"] == 3
    assert report["winners"] == 2
    assert report["losers"] == 1
    assert report["total_return_pct"] == pytest.approx(6.0)
