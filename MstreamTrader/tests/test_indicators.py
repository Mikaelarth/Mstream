"""
Tests pytest : indicateurs techniques (pure math).

Critique car CHAQUE module en aval (signals, regime, ensemble, MTF, backtest)
dépend de ces calculs. Un bug ici = systémique.

Stratégie de test :
  - Données déterministes (constantes, monotones, oscillations connues)
  - Vérifie alignement de la sortie avec l'entrée (longueurs)
  - Vérifie les warm-ups (None) au début
  - Vérifie les bornes connues (RSI ∈ [0, 100], stoch ∈ [0, 100])
  - Vérifie les cas limites (prix constants, série trop courte)
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.indicators import (
    sma, ema, rsi, macd, bollinger_bands, atr, stochastic,
    volume_trend, support_resistance, compute_all,
)


# ─── SMA ──────────────────────────────────────────────────────────────────────

def test_sma_constant_series():
    """Prix constants → SMA = constante après warm-up."""
    out = sma([10.0] * 20, period=5)
    assert out[:4] == [None, None, None, None]
    assert all(v == 10.0 for v in out[4:])


def test_sma_alignment():
    """Longueur de sortie == longueur d'entrée."""
    out = sma(list(range(50)), period=10)
    assert len(out) == 50
    assert out[:9] == [None] * 9
    # SMA(10) sur les 10 derniers index 40..49 = (40+...+49)/10 = 44.5
    assert out[49] == pytest.approx(44.5)


# ─── EMA ──────────────────────────────────────────────────────────────────────

def test_ema_constant_series():
    """EMA d'une série constante converge vers cette constante."""
    out = ema([100.0] * 30, period=10)
    assert out[9] == pytest.approx(100.0)
    assert all(v == pytest.approx(100.0) for v in out[9:])


def test_ema_too_short_returns_empty():
    assert ema([1.0, 2.0], period=10) == []


def test_ema_alignment_with_padding():
    out = ema(list(range(50)), period=10)
    assert len(out) == 50
    assert out[:9] == [None] * 9
    assert out[9] is not None


# ─── RSI ──────────────────────────────────────────────────────────────────────

def test_rsi_constant_series_no_movement():
    """Prix constants → pas de gain ni perte → avg_loss=0 → RSI=100."""
    out = rsi([50.0] * 30, period=14)
    # Premières 14 valeurs sont None (warm-up)
    assert out[:14] == [None] * 14
    # Toutes valeurs après doivent être 100 (pas de perte)
    assert all(v == 100.0 for v in out[14:])


def test_rsi_monotonic_increase_high_value():
    """Série strictement croissante → RSI doit tendre vers 100."""
    prices = list(range(1, 50))   # 1, 2, 3, ..., 49
    out = rsi([float(p) for p in prices], period=14)
    last = out[-1]
    assert last is not None
    assert last >= 99.0   # quasi tous gains, aucune perte


def test_rsi_monotonic_decrease_low_value():
    """Série strictement décroissante → RSI doit tendre vers 0."""
    prices = list(range(50, 1, -1))
    out = rsi([float(p) for p in prices], period=14)
    last = out[-1]
    assert last is not None
    assert last <= 1.0


def test_rsi_bounds_respected():
    """RSI ∈ [0, 100] toujours, peu importe l'input."""
    import random
    random.seed(0)
    prices = [100 + random.gauss(0, 5) for _ in range(100)]
    out = rsi(prices, period=14)
    for v in out:
        if v is not None:
            assert 0.0 <= v <= 100.0


def test_rsi_too_short_all_none():
    out = rsi([1.0, 2.0, 3.0], period=14)
    assert out == [None, None, None]


# ─── MACD ─────────────────────────────────────────────────────────────────────

def test_macd_alignment():
    prices = [float(i) for i in range(60)]
    res = macd(prices)
    assert len(res["macd"]) == 60
    assert len(res["signal"]) == 60
    assert len(res["histogram"]) == 60


def test_macd_constant_series_zero():
    """Prix constants → MACD = 0 sur tous les points calculables."""
    res = macd([100.0] * 60)
    non_none = [v for v in res["macd"] if v is not None]
    assert all(v == pytest.approx(0.0) for v in non_none)


def test_macd_histogram_is_diff():
    """Histogramme = MACD - Signal partout où les 2 sont définis."""
    prices = [float(i) + (i % 5) for i in range(60)]
    res = macd(prices)
    for m, s, h in zip(res["macd"], res["signal"], res["histogram"]):
        if m is not None and s is not None:
            assert h == pytest.approx(m - s)
        else:
            assert h is None


# ─── Bollinger Bands ──────────────────────────────────────────────────────────

def test_bb_constant_series_zero_std():
    """Prix constants → upper == middle == lower."""
    res = bollinger_bands([50.0] * 30, period=20)
    for u, m, l in zip(res["upper"], res["middle"], res["lower"]):
        if u is not None:
            assert u == pytest.approx(m)
            assert l == pytest.approx(m)


def test_bb_upper_above_middle_above_lower():
    """Sur série non-constante : upper > middle > lower."""
    import random
    random.seed(1)
    prices = [100 + random.gauss(0, 2) for _ in range(50)]
    res = bollinger_bands(prices, period=20)
    for u, m, l in zip(res["upper"], res["middle"], res["lower"]):
        if u is not None:
            assert u > m
            assert m > l


def test_bb_bandwidth_positive():
    prices = [100 + (i % 7) for i in range(40)]
    res = bollinger_bands(prices, period=20)
    for bw in res["bandwidth"]:
        if bw is not None:
            assert bw >= 0


# ─── ATR ──────────────────────────────────────────────────────────────────────

def test_atr_constant_series_zero():
    """Pas de mouvement → ATR = 0."""
    closes = [100.0] * 30
    out = atr(closes, closes, closes, period=14)
    non_none = [v for v in out if v is not None]
    assert all(v == pytest.approx(0.0) for v in non_none)


def test_atr_positive_with_volatility():
    closes = [float(100 + i % 5) for i in range(30)]
    highs  = [c + 1 for c in closes]
    lows   = [c - 1 for c in closes]
    out = atr(highs, lows, closes, period=14)
    last = out[-1]
    assert last is not None and last > 0


def test_atr_too_short():
    out = atr([1.0], [1.0], [1.0], period=14)
    assert all(v is None for v in out)


# ─── Stochastic ───────────────────────────────────────────────────────────────

def test_stochastic_bounds():
    """%K ∈ [0, 100]."""
    import random
    random.seed(2)
    closes = [100 + random.gauss(0, 3) for _ in range(50)]
    highs = [c + abs(random.gauss(0, 1)) for c in closes]
    lows = [c - abs(random.gauss(0, 1)) for c in closes]
    res = stochastic(highs, lows, closes)
    for k in res["k"]:
        if k is not None:
            assert 0.0 <= k <= 100.0


def test_stochastic_high_low_equal_returns_50():
    """Si high == low (pas de range), %K = 50 (sentinel)."""
    closes = [100.0] * 30
    res = stochastic(closes, closes, closes, k_period=14)
    non_none = [v for v in res["k"] if v is not None]
    assert all(v == 50.0 for v in non_none)


def test_stochastic_at_top_of_range():
    """Close == high de la fenêtre → K = 100."""
    closes = list(range(1, 30))
    highs = closes[:]   # close == high
    lows = [c - 5 for c in closes]
    res = stochastic([float(h) for h in highs],
                     [float(l) for l in lows],
                     [float(c) for c in closes], k_period=14)
    last = res["k"][-1]
    assert last == pytest.approx(100.0)


# ─── Volume trend ─────────────────────────────────────────────────────────────

def test_volume_trend_high_low_normal():
    base = [100.0] * 25
    out = volume_trend(base, period=20)
    # Tous NORMAL après warm-up (volume == moyenne)
    assert out[19] == "NORMAL"

    spike = base + [200.0]   # > 1.5× la moyenne (100) → HIGH
    out2 = volume_trend(spike, period=20)
    assert out2[-1] == "HIGH"

    drop = base + [10.0]   # < 0.5× la moyenne (100) → LOW
    out3 = volume_trend(drop, period=20)
    assert out3[-1] == "LOW"


# ─── Support / Resistance ─────────────────────────────────────────────────────

def test_support_resistance_detects_extrema():
    # Forme V : support local au milieu
    prices = [10, 9, 8, 7, 6, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
              14, 13, 12, 11, 10]
    sr = support_resistance([float(p) for p in prices], window=3)
    # Le creux à 5 doit être un support
    assert 5.0 in sr["supports"]
    # Le sommet à 15 doit être une résistance
    assert 15.0 in sr["resistances"]


# ─── compute_all ──────────────────────────────────────────────────────────────

def test_compute_all_returns_empty_for_short_series():
    candles = [
        {"open": 1, "high": 1.1, "low": 0.9, "close": 1.0, "timestamp": i}
        for i in range(10)
    ]
    assert compute_all(candles) == {}


def test_compute_all_returns_full_dict_for_sufficient_data():
    candles = [
        {"open": 100 + i, "high": 100 + i + 1, "low": 100 + i - 1,
         "close": 100 + i, "timestamp": i}
        for i in range(60)
    ]
    res = compute_all(candles)
    expected_keys = {
        "rsi", "macd_line", "macd_signal", "macd_histogram",
        "bb_upper", "bb_middle", "bb_lower", "bb_bandwidth",
        "atr", "stoch_k", "stoch_d", "ema_12", "ema_26", "ema_50",
        "sma_20", "sma_50", "current_price", "supports", "resistances",
    }
    assert expected_keys.issubset(res.keys())
    # Les indicateurs principaux ne doivent pas être None
    for k in ("rsi", "macd_line", "bb_upper", "atr", "ema_12"):
        assert res[k] is not None
    # current_price = dernier close
    assert res["current_price"] == 100 + 59
