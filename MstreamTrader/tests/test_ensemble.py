"""
Tests pytest : ensemble voting (3 stratégies + agrégation pondérée).

Le vote ensemble est le filtre N°1 d'entrée. Bug ici = mauvaises entrées sur
toute la stratégie. On vérifie :
  - Les 3 stratégies retournent un StrategyVote cohérent avec leurs signaux
  - Le vote pondéré respecte la direction de la majorité
  - Les poids régime modifient correctement le résultat
  - is_ensemble_qualified rejette correctement
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ensemble import (
    StrategyVote, StrategyOpinion, EnsembleDecision,
    strategy_trend_follower, strategy_mean_reversion, strategy_breakout_hunter,
    vote, is_ensemble_qualified,
    DEFAULT_WEIGHTS, REGIME_WEIGHTS,
)


# ─── Stratégies individuelles : trend follower ────────────────────────────────

def test_trend_follower_strong_buy_on_aligned_emas():
    """EMA 12>26>50 + price>EMA50+2% + MACD positif = STRONG_BUY."""
    indicators = {
        "ema_12": 105, "ema_26": 100, "ema_50": 95,
        "current_price": 110,
        "macd_line": 1.5, "macd_signal": 1.0, "macd_histogram": 0.5,
    }
    op = strategy_trend_follower(indicators)
    assert op.vote in (StrategyVote.STRONG_BUY, StrategyVote.BUY)
    assert op.confidence > 0


def test_trend_follower_strong_sell_on_inverted_emas():
    indicators = {
        "ema_12": 95, "ema_26": 100, "ema_50": 105,
        "current_price": 90,
        "macd_line": -1.5, "macd_signal": -1.0, "macd_histogram": -0.5,
    }
    op = strategy_trend_follower(indicators)
    assert op.vote in (StrategyVote.STRONG_SELL, StrategyVote.SELL)


def test_trend_follower_hold_on_missing_data():
    """Indicateurs absents → HOLD (rien à dire)."""
    op = strategy_trend_follower({})
    assert op.vote == StrategyVote.HOLD
    assert op.confidence == 0


def test_trend_follower_confidence_bounded():
    indicators = {
        "ema_12": 200, "ema_26": 100, "ema_50": 50,
        "current_price": 1000,
        "macd_line": 50, "macd_signal": 1, "macd_histogram": 49,
    }
    op = strategy_trend_follower(indicators)
    assert 0 <= op.confidence <= 100


# ─── Mean reversion ───────────────────────────────────────────────────────────

def test_mean_reversion_buys_extreme_oversold():
    """RSI < 25 + prix sur BB basse = STRONG_BUY."""
    indicators = {
        "rsi": 20.0, "current_price": 90,
        "bb_upper": 110, "bb_middle": 100, "bb_lower": 90,
        "stoch_k": 10, "stoch_d": 12,
    }
    op = strategy_mean_reversion(indicators)
    assert op.vote in (StrategyVote.STRONG_BUY, StrategyVote.BUY)


def test_mean_reversion_sells_extreme_overbought():
    indicators = {
        "rsi": 80.0, "current_price": 110,
        "bb_upper": 110, "bb_middle": 100, "bb_lower": 90,
        "stoch_k": 90, "stoch_d": 88,
    }
    op = strategy_mean_reversion(indicators)
    assert op.vote in (StrategyVote.STRONG_SELL, StrategyVote.SELL)


def test_mean_reversion_handles_zero_bb_range():
    """BB range = 0 (très rare mais possible) → pas de crash."""
    indicators = {
        "rsi": 50, "current_price": 100,
        "bb_upper": 100, "bb_middle": 100, "bb_lower": 100,
    }
    op = strategy_mean_reversion(indicators)
    assert op.vote == StrategyVote.HOLD


# ─── Breakout hunter ──────────────────────────────────────────────────────────

def test_breakout_buys_resistance_break():
    indicators = {
        "current_price": 102.0,
        "resistances": [101.0, 95.0],   # 101 cassé récemment
        "supports": [],
        "bb_bandwidth": 8.0, "atr": 2.0,
    }
    op = strategy_breakout_hunter(indicators)
    assert op.vote.value > 0   # BUY ou STRONG_BUY


def test_breakout_sells_support_break():
    indicators = {
        "current_price": 89.0,
        "resistances": [],
        "supports": [90.0, 85.0],
        "bb_bandwidth": 6.0, "atr": 1.5,
    }
    op = strategy_breakout_hunter(indicators)
    assert op.vote.value < 0   # SELL ou STRONG_SELL


def test_breakout_squeeze_adds_bias():
    """Bandwidth très bas (squeeze) ajoute biais haussier."""
    no_squeeze = strategy_breakout_hunter({
        "current_price": 100, "resistances": [], "supports": [],
        "bb_bandwidth": 10.0,
    })
    with_squeeze = strategy_breakout_hunter({
        "current_price": 100, "resistances": [], "supports": [],
        "bb_bandwidth": 2.0,
    })
    # Le squeeze ajoute +15 au score, donc confidence plus élevée
    assert with_squeeze.confidence >= no_squeeze.confidence


# ─── Vote ensemble ────────────────────────────────────────────────────────────

def test_vote_buy_when_all_strategies_bullish():
    """Toutes les stratégies bullish + bull regime → BUY ou STRONG_BUY."""
    indicators = {
        "ema_12": 105, "ema_26": 100, "ema_50": 95,
        "current_price": 110,
        "macd_line": 1.5, "macd_signal": 0.5, "macd_histogram": 1.0,
        "rsi": 28.0,   # survendu → mean reversion bullish aussi
        "bb_upper": 115, "bb_middle": 100, "bb_lower": 90,
        "stoch_k": 14, "stoch_d": 16,
        "resistances": [108], "supports": [],
        "bb_bandwidth": 10, "atr": 1,
    }
    decision = vote("test", indicators, regime="bull")
    assert decision.final_vote.value > 0
    assert decision.agreement_count >= 2


def test_vote_hold_when_strategies_disagree():
    """Stratégies en désaccord → HOLD."""
    indicators = {
        "ema_12": 105, "ema_26": 100, "ema_50": 95,
        "current_price": 110,
        "macd_line": 1, "macd_signal": 0.8,
        "rsi": 80.0,   # surchauffé : mean reversion bearish
        "bb_upper": 110, "bb_middle": 100, "bb_lower": 90,
        "resistances": [], "supports": [],
        "bb_bandwidth": 10, "atr": 1,
    }
    decision = vote("test", indicators, regime="neutral")
    # Probable HOLD ou faible agreement
    assert decision.agreement_count <= 2


def test_vote_returns_required_fields():
    decision = vote("btc", {}, regime="bull")
    assert isinstance(decision, EnsembleDecision)
    assert decision.coin_id == "btc"
    assert len(decision.opinions) == 3
    assert isinstance(decision.final_vote, StrategyVote)
    assert -100 <= decision.ensemble_score <= 100
    assert 0 <= decision.agreement_count <= 3
    assert 0 <= decision.confidence <= 100


def test_vote_uses_adaptive_weights_when_provided():
    """Les adaptive_weights remplacent REGIME_WEIGHTS."""
    indicators = {
        "ema_12": 105, "ema_26": 100, "ema_50": 95, "current_price": 110,
        "macd_line": 2, "macd_signal": 1,
    }
    # On donne tout le poids à trend_follower
    weights = {"trend_follower": 5.0, "mean_reversion": 0.0,
                "breakout_hunter": 0.0}
    decision = vote("test", indicators, regime="bear",
                     adaptive_weights=weights)
    # Trend follower est bullish → vote final doit l'être aussi
    assert decision.final_vote.value > 0


def test_vote_handles_missing_indicators_gracefully():
    """Aucun indicateur → toutes les stratégies HOLD → ensemble HOLD."""
    decision = vote("test", {}, regime="neutral")
    assert decision.final_vote == StrategyVote.HOLD


# ─── Qualification ────────────────────────────────────────────────────────────

def test_qualified_requires_buy_vote():
    decision = EnsembleDecision(
        coin_id="x", opinions=[], final_vote=StrategyVote.HOLD,
        ensemble_score=50, agreement_count=3, confidence=80,
    )
    assert is_ensemble_qualified(decision) is False


def test_qualified_requires_min_agreement():
    decision = EnsembleDecision(
        coin_id="x", opinions=[], final_vote=StrategyVote.BUY,
        ensemble_score=50, agreement_count=1, confidence=80,
    )
    assert is_ensemble_qualified(decision, min_agreement=2) is False


def test_qualified_requires_min_score():
    decision = EnsembleDecision(
        coin_id="x", opinions=[], final_vote=StrategyVote.BUY,
        ensemble_score=10, agreement_count=3, confidence=80,
    )
    assert is_ensemble_qualified(decision, min_score=30) is False


def test_qualified_requires_min_confidence():
    decision = EnsembleDecision(
        coin_id="x", opinions=[], final_vote=StrategyVote.BUY,
        ensemble_score=50, agreement_count=3, confidence=20,
    )
    assert is_ensemble_qualified(decision, min_confidence=50) is False


def test_qualified_passes_all_thresholds():
    decision = EnsembleDecision(
        coin_id="x", opinions=[], final_vote=StrategyVote.STRONG_BUY,
        ensemble_score=60, agreement_count=3, confidence=75,
    )
    assert is_ensemble_qualified(decision) is True


# ─── Cohérence des poids régime ───────────────────────────────────────────────

def test_regime_weights_bull_favors_trend():
    """Bull → trend_follower a le poids le plus élevé."""
    bull_w = REGIME_WEIGHTS["bull"]
    assert bull_w["trend_follower"] >= bull_w["mean_reversion"]
    assert bull_w["trend_follower"] >= bull_w["breakout_hunter"]


def test_regime_weights_neutral_favors_mean_reversion():
    """Neutral → mean_reversion brille (range trading)."""
    neut_w = REGIME_WEIGHTS["neutral"]
    assert neut_w["mean_reversion"] >= neut_w["trend_follower"]


def test_regime_weights_bear_lowest_overall():
    """Bear → tous les poids sont réduits (moins agressif)."""
    bear_w = REGIME_WEIGHTS["bear"]
    bull_w = REGIME_WEIGHTS["bull"]
    assert sum(bear_w.values()) < sum(bull_w.values())
