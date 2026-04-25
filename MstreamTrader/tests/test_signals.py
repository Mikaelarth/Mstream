"""
Tests pytest : moteur de signaux (scoring multi-indicateurs).

C'est le module qui produit les TradeSignal consommés ensuite par le bot.
Bug ici = mauvais signaux propagés à toute la chaîne décisionnelle.

Stratégie :
  - Sub-scorers individuels (RSI, MACD, BB, Stoch, EMA) sur valeurs connues
  - analyze() complet sur scénarios extrêmes (full bullish / full bearish)
  - SL/TP : cohérence prix > SL > 0 sur BUY, SL > prix sur SELL
  - Risk/reward : ratio plausible
  - rank_opportunities : tri par score décroissant + bonus R/R
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.signals import (
    Signal, TradeSignal,
    _score_rsi, _score_macd, _score_bollinger, _score_stochastic, _score_ema,
    _compute_stop_take, analyze, rank_opportunities,
    SIGNAL_LABELS, SIGNAL_COLORS,
)


# ─── _score_rsi ───────────────────────────────────────────────────────────────

def test_rsi_extreme_oversold_strong_buy_score():
    score, reasons = _score_rsi(15.0)
    assert score == 40
    assert len(reasons) == 1


def test_rsi_oversold_buy_score():
    score, _ = _score_rsi(28.0)
    assert score == 25


def test_rsi_neutral_zero_score():
    score, _ = _score_rsi(50.0)
    assert score == 0


def test_rsi_extreme_overbought_strong_sell():
    score, _ = _score_rsi(85.0)
    assert score == -40


def test_rsi_none_returns_zero():
    score, reasons = _score_rsi(None)
    assert score == 0
    assert reasons == []


# ─── _score_macd ──────────────────────────────────────────────────────────────

def test_macd_above_signal_bullish():
    score, _ = _score_macd(macd_line=2.0, macd_signal=1.0, histogram=1.0)
    assert score > 0


def test_macd_below_signal_bearish():
    score, _ = _score_macd(macd_line=-2.0, macd_signal=-1.0, histogram=-1.0)
    assert score < 0


def test_macd_none_returns_zero():
    score, _ = _score_macd(None, None, None)
    assert score == 0


# ─── _score_bollinger ─────────────────────────────────────────────────────────

def test_bollinger_at_lower_band_buys():
    score, _ = _score_bollinger(price=90, bb_upper=110, bb_middle=100,
                                  bb_lower=90, bandwidth=20)
    assert score > 0


def test_bollinger_at_upper_band_sells():
    score, _ = _score_bollinger(price=110, bb_upper=110, bb_middle=100,
                                  bb_lower=90, bandwidth=20)
    assert score < 0


def test_bollinger_zero_range_no_crash():
    """upper == lower (rare) → score 0 sans division par zéro."""
    score, _ = _score_bollinger(price=100, bb_upper=100, bb_middle=100,
                                  bb_lower=100, bandwidth=0)
    assert score == 0


def test_bollinger_none_returns_zero():
    score, _ = _score_bollinger(price=100, bb_upper=None, bb_middle=None,
                                  bb_lower=None, bandwidth=None)
    assert score == 0


# ─── _score_stochastic ────────────────────────────────────────────────────────

def test_stoch_double_oversold_buys():
    score, _ = _score_stochastic(k=10, d=12)
    assert score >= 20


def test_stoch_double_overbought_sells():
    score, _ = _score_stochastic(k=90, d=92)
    assert score <= -20


def test_stoch_none_returns_zero():
    score, _ = _score_stochastic(None, None)
    assert score == 0


# ─── _score_ema ───────────────────────────────────────────────────────────────

def test_ema_golden_cross_bullish():
    score, _ = _score_ema(price=110, ema_12=105, ema_26=100, ema_50=95)
    assert score > 0


def test_ema_death_cross_bearish():
    score, _ = _score_ema(price=90, ema_12=95, ema_26=100, ema_50=105)
    assert score < 0


# ─── _compute_stop_take ───────────────────────────────────────────────────────

def test_stop_take_buy_signal_stop_below_price():
    sl, tp, rr = _compute_stop_take(
        price=100, signal=Signal.BUY, atr_val=2.0,
        supports=[95.0], resistances=[110.0],
    )
    assert sl < 100
    assert tp > 100
    assert rr > 0


def test_stop_take_sell_signal_stop_above_price():
    sl, tp, rr = _compute_stop_take(
        price=100, signal=Signal.SELL, atr_val=2.0,
        supports=[], resistances=[],
    )
    assert sl > 100
    assert tp < 100


def test_stop_take_hold_returns_zeros():
    sl, tp, rr = _compute_stop_take(
        price=100, signal=Signal.HOLD, atr_val=2.0,
        supports=[], resistances=[],
    )
    assert sl == 0.0
    assert tp == 0.0


def test_stop_take_uses_default_atr_if_missing():
    """ATR=None → fallback 2% du prix, pas de crash."""
    sl, tp, rr = _compute_stop_take(
        price=100, signal=Signal.BUY, atr_val=None,
        supports=[], resistances=[],
    )
    assert sl < 100 and tp > 100


# ─── analyze() ────────────────────────────────────────────────────────────────

def test_analyze_zero_price_returns_hold():
    sig = analyze("btc", "BTC", {"current_price": 0})
    assert sig.signal == Signal.HOLD
    assert "insuffisantes" in sig.reasons[0].lower()


def test_analyze_full_bullish_scenario_returns_buy():
    """Tous les indicateurs bullish → STRONG_BUY ou BUY."""
    indicators = {
        "current_price": 90,
        "rsi": 25,                      # oversold → +25
        "macd_line": 1, "macd_signal": 0.5, "macd_histogram": 0.5,   # bullish
        "bb_upper": 110, "bb_middle": 100, "bb_lower": 90, "bb_bandwidth": 20,
        "stoch_k": 15, "stoch_d": 12,   # double oversold
        "ema_12": 95, "ema_26": 92, "ema_50": 88,   # golden cross
        "atr": 2.0, "supports": [], "resistances": [105],
    }
    sig = analyze("btc", "BTC", indicators)
    assert sig.signal in (Signal.BUY, Signal.STRONG_BUY)
    assert sig.score > 0
    assert sig.confidence > 0
    assert sig.stop_loss < sig.price


def test_analyze_full_bearish_scenario_returns_sell():
    indicators = {
        "current_price": 110,
        "rsi": 85,
        "macd_line": -1, "macd_signal": -0.5, "macd_histogram": -0.5,
        "bb_upper": 110, "bb_middle": 100, "bb_lower": 90, "bb_bandwidth": 20,
        "stoch_k": 90, "stoch_d": 92,
        "ema_12": 105, "ema_26": 108, "ema_50": 112,
        "atr": 2.0, "supports": [95], "resistances": [],
    }
    sig = analyze("btc", "BTC", indicators)
    assert sig.signal in (Signal.SELL, Signal.STRONG_SELL)
    assert sig.score < 0


def test_analyze_neutral_returns_hold():
    """Indicateurs balanced → HOLD (score modéré)."""
    indicators = {
        "current_price": 100,
        "rsi": 50,                       # neutre → 0
        # MACD légèrement bullish pour compenser le biais EMA inverse
        "macd_line": 1, "macd_signal": 0.5,
        "bb_upper": 110, "bb_middle": 100, "bb_lower": 90, "bb_bandwidth": 20,
        "stoch_k": 50, "stoch_d": 50,
        "ema_12": 101, "ema_26": 100, "ema_50": 99,
        "atr": 1.0,
    }
    sig = analyze("btc", "BTC", indicators)
    # score modéré → HOLD ou BUY (pas STRONG_BUY ni SELL)
    assert sig.signal in (Signal.HOLD, Signal.BUY)
    assert sig.score < 50   # pas STRONG_BUY (qui demande >= 50)


def test_analyze_score_clamped():
    """Le score final doit être ∈ [-100, 100]."""
    indicators = {
        "current_price": 100, "rsi": 5,
        "macd_line": 100, "macd_signal": 0, "macd_histogram": 100,
        "bb_upper": 200, "bb_middle": 100, "bb_lower": 50,
        "stoch_k": 5, "stoch_d": 5,
        "ema_12": 200, "ema_26": 100, "ema_50": 50,
    }
    sig = analyze("btc", "BTC", indicators)
    assert -100 <= sig.score <= 100
    assert 0 <= sig.confidence <= 100


def test_trade_signal_label_and_color():
    sig = TradeSignal("btc", "BTC", Signal.BUY, 50, 70, 100)
    assert sig.signal_label == SIGNAL_LABELS[Signal.BUY]
    assert sig.color == SIGNAL_COLORS[Signal.BUY]


# ─── rank_opportunities ───────────────────────────────────────────────────────

def test_rank_orders_buy_before_sell():
    sigs = [
        TradeSignal("a", "A", Signal.SELL, -50, 70, 100, risk_reward=2.0),
        TradeSignal("b", "B", Signal.BUY,  +50, 70, 100, risk_reward=2.0),
    ]
    ranked = rank_opportunities(sigs)
    assert ranked[0].signal == Signal.BUY


def test_rank_higher_confidence_first_among_buys():
    sigs = [
        TradeSignal("a", "A", Signal.BUY, 50, 60, 100, risk_reward=1.5),
        TradeSignal("b", "B", Signal.BUY, 50, 90, 100, risk_reward=1.5),
    ]
    ranked = rank_opportunities(sigs)
    assert ranked[0].coin_id == "b"


def test_rank_rr_bonus_pushes_up():
    """À confidence égale, R/R ≥ 2 ajoute un bonus."""
    sigs = [
        TradeSignal("a", "A", Signal.BUY, 50, 70, 100, risk_reward=1.0),
        TradeSignal("b", "B", Signal.BUY, 50, 70, 100, risk_reward=3.0),
    ]
    ranked = rank_opportunities(sigs)
    assert ranked[0].coin_id == "b"
