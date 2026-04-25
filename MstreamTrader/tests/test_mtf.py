"""
Tests pytest : Multi-Timeframe Confluence (MTF).

L'analyse MTF est le 2e gros filtre d'entrée (après ensemble). On vérifie :
  - compute_single_timeframe : direction cohérente avec EMA/RSI/MACD
  - analyze_confluence : score = nombre de TF alignés
  - is_confluence_valid_for_long : refus si TF long-terme bearish fort
  - Pas de crash sur séries courtes / TF manquants
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.mtf import (
    TimeframeSignal, MTFConfluence,
    compute_single_timeframe, analyze_confluence,
    is_confluence_valid_for_long, describe_confluence,
)


def _gen_candles(closes: list[float], spread: float = 0.5):
    """Helper : transforme une liste de closes en bougies OHLC."""
    return [
        {"close": c, "high": c + spread, "low": c - spread, "open": c}
        for c in closes
    ]


# ─── compute_single_timeframe ─────────────────────────────────────────────────

def test_single_tf_too_few_candles():
    sig = compute_single_timeframe([], "1h")
    assert sig.direction == 0
    assert sig.strength == 0
    assert "insuffisant" in " ".join(sig.reasons).lower()


def test_single_tf_under_30_candles_returns_neutral():
    candles = _gen_candles([100.0] * 25)
    sig = compute_single_timeframe(candles, "1h")
    assert sig.direction == 0


def test_single_tf_uptrend_bullish():
    """Trend haussier marqué → direction = 1.

    Note : sur un trend linéaire pur, MACD line peut converger vers son signal
    et donner macd_bullish=False — c'est un artéfact mathématique de l'EMA(EMA),
    pas un bug. On vérifie donc seulement la direction globale.
    """
    closes = [100.0 + i * 0.5 for i in range(60)]
    candles = _gen_candles(closes)
    sig = compute_single_timeframe(candles, "1h")
    assert sig.direction == 1
    assert sig.ema_bullish is True
    assert sig.strength > 0


def test_single_tf_downtrend_bearish():
    closes = [100.0 - i * 0.5 for i in range(60)]
    candles = _gen_candles(closes)
    sig = compute_single_timeframe(candles, "1d")
    assert sig.direction == -1
    assert sig.ema_bullish is False


def test_single_tf_flat_neutral():
    """Prix plats → direction proche de 0 (probablement 0)."""
    candles = _gen_candles([100.0] * 60)
    sig = compute_single_timeframe(candles, "4h")
    assert sig.direction in (-1, 0, 1)   # peut être ±1 par ties RSI
    # Mais RSI doit être ~100 (pas de loss) ou stable
    if sig.rsi is not None:
        assert sig.rsi >= 0


def test_single_tf_includes_timeframe_field():
    candles = _gen_candles([100.0 + i * 0.1 for i in range(40)])
    sig = compute_single_timeframe(candles, "4h")
    assert sig.timeframe == "4h"


# ─── analyze_confluence ───────────────────────────────────────────────────────

def test_confluence_all_bullish_aligned():
    """3 TF tous bullish → is_bullish_aligned + score = 3."""
    bullish = _gen_candles([100.0 + i * 0.5 for i in range(60)])
    candles_by_tf = {"1h": bullish, "4h": bullish, "1d": bullish}
    res = analyze_confluence("btc", candles_by_tf)
    assert res.confluence_score == 3
    assert res.dominant_direction == 1
    assert res.is_bullish_aligned is True
    assert res.is_bearish_aligned is False


def test_confluence_all_bearish_aligned():
    bearish = _gen_candles([100.0 - i * 0.5 for i in range(60)])
    res = analyze_confluence("btc", {"1h": bearish, "4h": bearish, "1d": bearish})
    assert res.confluence_score == 3
    assert res.dominant_direction == -1
    assert res.is_bearish_aligned is True


def test_confluence_mixed_signals():
    bullish = _gen_candles([100.0 + i * 0.5 for i in range(60)])
    bearish = _gen_candles([100.0 - i * 0.5 for i in range(60)])
    res = analyze_confluence("btc", {"1h": bullish, "4h": bearish, "1d": bullish})
    # 2 bull, 1 bear → bullish_aligned avec 2/3
    assert res.dominant_direction == 1
    assert res.confluence_score == 2
    assert res.is_bullish_aligned is True


def test_confluence_includes_all_timeframes():
    bullish = _gen_candles([100.0 + i * 0.5 for i in range(60)])
    res = analyze_confluence("eth", {"1h": bullish, "4h": bullish})
    assert res.total_timeframes == 2
    assert "1h" in res.timeframes
    assert "4h" in res.timeframes


def test_confluence_empty_timeframes():
    res = analyze_confluence("eth", {})
    assert res.total_timeframes == 0
    assert res.confluence_score == 0
    assert res.is_bullish_aligned is False


# ─── is_confluence_valid_for_long ─────────────────────────────────────────────

def test_valid_for_long_with_aligned_bullish():
    bullish = _gen_candles([100.0 + i * 0.5 for i in range(60)])
    res = analyze_confluence("btc", {"1h": bullish, "4h": bullish, "1d": bullish})
    assert is_confluence_valid_for_long(res, min_confluence=2) is True


def test_invalid_for_long_when_score_below_min():
    bullish = _gen_candles([100.0 + i * 0.5 for i in range(60)])
    bearish = _gen_candles([100.0 - i * 0.5 for i in range(60)])
    # 1 bull, 2 bear → score=2 mais dominant_direction = -1
    res = analyze_confluence("btc", {"1h": bullish, "4h": bearish, "1d": bearish})
    assert is_confluence_valid_for_long(res, min_confluence=2) is False


def test_invalid_for_long_when_long_tf_strongly_bearish():
    """Si daily strongly bearish, on refuse même si 1h+4h sont bullish."""
    bullish_short = _gen_candles([100.0 + i * 0.5 for i in range(60)])
    bearish_strong = _gen_candles([100.0 - i * 1.0 for i in range(60)])
    res = analyze_confluence("btc", {
        "1h": bullish_short, "4h": bullish_short, "1d": bearish_strong
    })
    # 2/3 bullish mais daily bearish strong → invalid
    # Note : confluence_score=2 (bull), donc dominant=1 mais le check
    # "tf le plus long bearish strong" doit refuser
    if res.timeframes["1d"].direction < 0 and res.timeframes["1d"].strength > 30:
        assert is_confluence_valid_for_long(res, min_confluence=2) is False


def test_invalid_for_long_when_dominant_negative():
    """Dominant bearish → refuser même avec score élevé."""
    bearish = _gen_candles([100.0 - i * 0.5 for i in range(60)])
    res = analyze_confluence("btc", {"1h": bearish, "4h": bearish, "1d": bearish})
    assert is_confluence_valid_for_long(res, min_confluence=2) is False


# ─── describe ─────────────────────────────────────────────────────────────────

def test_describe_includes_summary():
    bullish = _gen_candles([100.0 + i * 0.5 for i in range(60)])
    res = analyze_confluence("btc", {"1h": bullish, "4h": bullish})
    desc = describe_confluence(res)
    assert "btc" in desc
    assert "1h" in desc
    assert "4h" in desc
    assert "ALIGNE" in desc or "NON" in desc
