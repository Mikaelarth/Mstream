"""
Tests pytest : walk-forward analysis (validation hors-sample).

Le module utilise Backtest réel — chaque happy-path test prend ~30-60s.
On garde donc UN seul test happy-path qui couvre la structure complète,
et plusieurs edge cases (validations rapides).

Les vrais runs de validation se font via la CLI : `optimize_params.py --walk-forward`.
"""

import pytest
import sys
import os
import random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.adaptive as ad_mod
import core.circuit_breaker as cb_mod
from core import database
from core.walk_forward import (
    run_walk_forward, WalkForwardResult, WalkForwardWindow,
)
from core.backtest import BacktestConfig


@pytest.fixture(autouse=True)
def clean_state():
    ad_mod._instance = None
    cb_mod._instance = None
    database.init_db()


def _gen_candles(n: int = 800, start: float = 100.0, seed: int = 42):
    """Génère n bougies horaires (800 = ~33 jours en 1h)."""
    random.seed(seed)
    out = []
    price = start
    ts = 1700000000.0
    for i in range(n):
        change = random.gauss(0.0005, 0.015)
        new_p = price * (1 + change)
        out.append({
            "timestamp": ts, "open": price,
            "high": max(price, new_p) * 1.005,
            "low":  min(price, new_p) * 0.995,
            "close": new_p,
        })
        price = new_p
        ts += 3600
    return out


# ─── Edge cases (rapides) ─────────────────────────────────────────────────────

def test_walk_forward_empty_data_returns_empty_result():
    cfg = BacktestConfig(initial_capital=1000)
    result = run_walk_forward({}, cfg, verbose=False)
    assert isinstance(result, WalkForwardResult)
    assert result.n_windows == 0


def test_walk_forward_too_few_candles_raises():
    """< 100 timestamps communs → ValueError."""
    cfg = BacktestConfig(initial_capital=1000)
    coins_data = {"btc": _gen_candles(n=50)}
    with pytest.raises(ValueError, match="Pas assez"):
        run_walk_forward(coins_data, cfg, verbose=False)


def test_walk_forward_history_too_short_raises():
    """Historique < 1.5 × window_days → ValueError."""
    cfg = BacktestConfig(initial_capital=1000)
    # 600 candles 1h = 25 jours, window=20 → besoin 30j → ValueError
    coins_data = {"btc": _gen_candles(n=600)}
    with pytest.raises(ValueError, match="insuffisant"):
        run_walk_forward(coins_data, cfg, window_days=20, step_days=10,
                          verbose=False)


# ─── Happy path (1 test consolidé, ~30s) ──────────────────────────────────────

def test_walk_forward_full_pipeline_smoke():
    """Smoke test : lance walk-forward sur données minimales et vérifie la structure."""
    cfg = BacktestConfig(
        initial_capital=1000.0,
        candle_duration_sec=3600,
        periods_per_year=8760,
        cooldown_candles=6,
        min_score=25.0, min_confidence=30.0, min_rr=1.5,
    )
    coins_data = {"btc": _gen_candles(n=800, seed=1)}
    result = run_walk_forward(
        coins_data, cfg,
        window_days=20, step_days=10,
        train_ratio=0.7, verbose=False,
    )
    assert isinstance(result, WalkForwardResult)

    # Si des fenêtres ont tourné, vérifier toutes les invariantes en un seul test
    if result.n_windows > 0:
        # Structure des fenêtres
        for w in result.windows:
            assert isinstance(w, WalkForwardWindow)
            assert w.start_ts < w.test_start_ts < w.end_ts

        # Métriques agrégées présentes
        expected_keys = {
            "avg_return_pct", "std_return", "avg_sharpe",
            "avg_profit_factor", "avg_max_dd", "total_trades",
            "windows_positive", "windows_negative", "consistency_pct",
        }
        assert expected_keys.issubset(result.aggregated_metrics.keys())

        # Consistency_score borné
        assert 0.0 <= result.consistency_score <= 1.0

        # is_robust cohérent avec les seuils (consistency>0.6 ET sharpe>0.5 ET pf>1.2)
        if not result.is_robust:
            agg = result.aggregated_metrics
            assert (result.consistency_score <= 0.6
                    or agg["avg_sharpe"] <= 0.5
                    or agg["avg_profit_factor"] <= 1.2)
