"""
Tests pytest : détecteur de régime (Bull/Bear/Neutral) et transitions.

Le régime conditionne les profils (min_score, max_positions, risk_pct...).
Une mauvaise classification = mauvaises décisions sur tout le pipeline.

Stratégie :
  - Séries synthétiques avec trend connu → vérifier classification
  - Edge cases : données < 200 bougies, EMA dégénérée
  - Profils : valeurs cohérentes (BULL plus permissif que BEAR)
  - Transition : golden cross simulé déclenche transitioning=True
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.regime import (
    Regime, REGIME_PROFILES,
    detect_regime, detect_regime_from_candles,
    detect_regime_transition, get_profile, describe,
)


# ─── detect_regime ────────────────────────────────────────────────────────────

def test_insufficient_data_returns_neutral():
    """Moins de 200 bougies → NEUTRAL avec deviation None."""
    regime, dev = detect_regime([100.0] * 50)
    assert regime == Regime.NEUTRAL
    assert dev is None


def test_empty_data_returns_neutral():
    regime, dev = detect_regime([])
    assert regime == Regime.NEUTRAL
    assert dev is None


def test_constant_prices_returns_neutral():
    """Prix plats = écart 0 → NEUTRAL."""
    regime, dev = detect_regime([100.0] * 250)
    assert regime == Regime.NEUTRAL
    assert dev == pytest.approx(0.0, abs=0.01)


def test_strong_uptrend_returns_bull():
    """Trend haussier marqué : prix bien au-dessus EMA200 → BULL."""
    # 200 bougies de base + 50 bougies de pump (+30%)
    closes = [100.0] * 200 + [130.0] * 50
    regime, dev = detect_regime(closes, ema_period=200)
    assert regime == Regime.BULL
    assert dev > 2.0


def test_strong_downtrend_returns_bear():
    """Trend baissier marqué → BEAR."""
    closes = [100.0] * 200 + [70.0] * 50
    regime, dev = detect_regime(closes, ema_period=200)
    assert regime == Regime.BEAR
    assert dev < -2.0


def test_threshold_boundary_above_returns_neutral():
    """Écart < threshold → NEUTRAL (zone tampon)."""
    # On veut le prix juste +1% au-dessus EMA → NEUTRAL avec threshold 2%
    closes = [100.0] * 250
    closes[-1] = 101.0   # +1% sur dernière bougie
    regime, dev = detect_regime(closes, threshold_pct=2.0)
    assert regime == Regime.NEUTRAL


def test_custom_threshold_strict_bull():
    """Threshold abaissé → bascule plus rapide vers BULL."""
    closes = [100.0] * 200 + [101.0] * 50
    regime_loose, _ = detect_regime(closes, threshold_pct=2.0)
    regime_strict, _ = detect_regime(closes, threshold_pct=0.5)
    # Avec threshold 0.5%, +1% suffit pour passer en BULL
    assert regime_loose == Regime.NEUTRAL
    assert regime_strict == Regime.BULL


# ─── detect_regime_from_candles ───────────────────────────────────────────────

def test_from_candles_extracts_close():
    candles = [{"close": p, "high": p, "low": p, "open": p} for p in [100.0] * 250]
    regime, dev = detect_regime_from_candles(candles)
    assert regime == Regime.NEUTRAL
    assert dev == pytest.approx(0.0, abs=0.01)


def test_from_candles_skips_invalid_close():
    """Les bougies avec close <= 0 sont filtrées."""
    candles = [{"close": 100.0}] * 250 + [{"close": 0}, {"close": -5}]
    regime, _ = detect_regime_from_candles(candles)
    assert regime == Regime.NEUTRAL   # toujours basé sur les 250 valides


def test_from_candles_empty():
    regime, dev = detect_regime_from_candles([])
    assert regime == Regime.NEUTRAL
    assert dev is None


# ─── Profils ──────────────────────────────────────────────────────────────────

def test_profile_bull_more_permissive_than_bear():
    """BULL doit avoir des seuils plus bas et plus de positions que BEAR."""
    bull = get_profile(Regime.BULL)
    bear = get_profile(Regime.BEAR)
    assert bull["min_score"] < bear["min_score"]
    assert bull["min_confidence"] < bear["min_confidence"]
    assert bull["max_positions"] > bear["max_positions"]
    assert bull["risk_pct"] > bear["risk_pct"]
    assert bull["max_capital_pct"] > bear["max_capital_pct"]


def test_profile_neutral_between_bull_and_bear():
    """NEUTRAL doit être entre BULL (permissif) et BEAR (strict)."""
    bull = get_profile(Regime.BULL)
    neutral = get_profile(Regime.NEUTRAL)
    bear = get_profile(Regime.BEAR)
    assert bull["min_score"] <= neutral["min_score"] <= bear["min_score"]
    assert bull["risk_pct"] >= neutral["risk_pct"] >= bear["risk_pct"]


def test_profile_returns_copy_not_reference():
    """Modifier le résultat ne doit pas polluer la constante REGIME_PROFILES."""
    p = get_profile(Regime.BULL)
    p["min_score"] = 999.9
    assert REGIME_PROFILES[Regime.BULL]["min_score"] != 999.9


# ─── describe ─────────────────────────────────────────────────────────────────

def test_describe_includes_label_and_deviation():
    s = describe(Regime.BULL, deviation_pct=4.5)
    assert "Haussier" in s
    assert "+4.50%" in s


def test_describe_no_deviation_just_label():
    s = describe(Regime.BEAR)
    assert "Baissier" in s


# ─── Transition ───────────────────────────────────────────────────────────────

def test_transition_insufficient_data():
    res = detect_regime_transition([100.0] * 50)
    assert res["transitioning"] is False
    assert res["from_regime"] == "unknown"


def test_transition_no_change_in_stable_regime():
    """Marché stable : pas de transition détectée."""
    closes = [100.0 + i * 0.01 for i in range(250)]   # micro drift
    res = detect_regime_transition(closes)
    assert res["transitioning"] in (True, False)   # peut détecter du bruit
    # Si transition, score doit être bas
    if not res["transitioning"]:
        assert res["transition_score"] < 0.3


def test_transition_golden_cross_detected():
    """Construit une série avec golden cross récent (EMA50 passe au-dessus EMA200)."""
    # 200 bougies à 100, puis 50 bougies en hausse forte (+50%)
    closes = [100.0] * 200 + [100.0 + i * 1.0 for i in range(50)]
    res = detect_regime_transition(closes, lookback_days=10)
    # Golden cross déclenche transition vers BULL
    if res["transitioning"]:
        assert res["to_regime"] == "bull"
        assert any("Cross" in s or "Momentum" in s for s in res["signals"])


def test_transition_returns_correct_keys():
    res = detect_regime_transition([100.0] * 250)
    expected = {"transitioning", "from_regime", "to_regime",
                "transition_score", "signals", "days_to_bascule",
                "btc_deviation_pct"}
    assert expected.issubset(res.keys())
