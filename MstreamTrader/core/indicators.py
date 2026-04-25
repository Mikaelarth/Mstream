"""
MstreamTrader - Indicateurs Techniques
Calculs mathématiques purs : RSI, MACD, Bollinger Bands, EMA, SMA, ATR, Stochastic
Aucune dépendance externe — compatible Android/Buildozer
"""


def _ema(prices: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema_values = []
    # Seed avec SMA
    seed = sum(prices[:period]) / period
    ema_values.append(seed)
    for price in prices[period:]:
        ema_values.append(price * k + ema_values[-1] * (1 - k))
    # Padding pour aligner sur la liste d'entrée
    return [None] * (period - 1) + ema_values


def sma(prices: list[float], period: int) -> list[float]:
    """Simple Moving Average."""
    result = [None] * (period - 1)
    for i in range(period - 1, len(prices)):
        result.append(sum(prices[i - period + 1: i + 1]) / period)
    return result


def ema(prices: list[float], period: int) -> list[float]:
    """EMA exposée publiquement."""
    return _ema(prices, period)


def rsi(prices: list[float], period: int = 14) -> list[float | None]:
    """
    Relative Strength Index (RSI).
    Retourne une liste de même longueur, None sur les premières valeurs.
    - RSI > 70 : Surachat (signal de vente potentiel)
    - RSI < 30 : Survente (signal d'achat potentiel)
    """
    if len(prices) < period + 1:
        return [None] * len(prices)

    result = [None] * period
    gains = []
    losses = []

    for i in range(1, period + 1):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(100 - (100 / (1 + rs)))

    for i in range(period + 1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gain = max(delta, 0)
        loss = max(-delta, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - (100 / (1 + rs)))

    return result


def macd(
    prices: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict:
    """
    MACD (Moving Average Convergence Divergence).
    Retourne: { 'macd': [...], 'signal': [...], 'histogram': [...] }
    - MACD croise au-dessus du signal : Momentum haussier (achat)
    - MACD croise en-dessous du signal : Momentum baissier (vente)
    """
    ema_fast = _ema(prices, fast)
    ema_slow = _ema(prices, slow)

    macd_line = []
    for f, s in zip(ema_fast, ema_slow):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(f - s)

    # Calculer la ligne signal sur les valeurs non-None
    valid_macd = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    signal_line = [None] * len(macd_line)

    if len(valid_macd) >= signal:
        values = [v for _, v in valid_macd]
        signal_ema = _ema(values, signal)
        for idx, (orig_i, _) in enumerate(valid_macd):
            if idx < len(signal_ema):
                signal_line[orig_i] = signal_ema[idx]

    histogram = []
    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(m - s)

    return {
        "macd":      macd_line,
        "signal":    signal_line,
        "histogram": histogram,
    }


def bollinger_bands(
    prices: list[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> dict:
    """
    Bandes de Bollinger.
    Retourne: { 'upper': [...], 'middle': [...], 'lower': [...], 'bandwidth': [...] }
    - Prix touche la bande supérieure : Zone de résistance
    - Prix touche la bande inférieure : Zone de support
    - Bandes resserrées (squeeze) : Explosion de volatilité imminente
    """
    middle = sma(prices, period)
    upper = [None] * len(prices)
    lower = [None] * len(prices)
    bandwidth = [None] * len(prices)

    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1: i + 1]
        avg = middle[i]
        variance = sum((p - avg) ** 2 for p in window) / period
        std = variance ** 0.5
        upper[i] = avg + std_dev * std
        lower[i] = avg - std_dev * std
        if avg != 0:
            bandwidth[i] = (upper[i] - lower[i]) / avg * 100

    return {
        "upper":     upper,
        "middle":    middle,
        "lower":     lower,
        "bandwidth": bandwidth,
    }


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    """
    Average True Range (ATR) — mesure la volatilité réelle.
    Plus l'ATR est élevé, plus le marché est volatile.
    """
    if len(closes) < 2:
        return [None] * len(closes)

    true_ranges = [None]
    for i in range(1, len(closes)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        true_ranges.append(max(hl, hc, lc))

    result = [None] * period
    if len(true_ranges) < period + 1:
        return [None] * len(closes)

    valid_tr = [v for v in true_ranges if v is not None]
    first_atr = sum(valid_tr[:period]) / period
    atr_values = [first_atr]

    for i in range(period, len(valid_tr)):
        atr_values.append((atr_values[-1] * (period - 1) + valid_tr[i]) / period)

    return result + atr_values


def stochastic(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    k_period: int = 14,
    d_period: int = 3,
) -> dict:
    """
    Oscillateur Stochastique (%K et %D).
    - %K > 80 : Surachat
    - %K < 20 : Survente
    - Croisement %K/%D : Signal fort
    """
    k_values = [None] * (k_period - 1)

    for i in range(k_period - 1, len(closes)):
        h = max(highs[i - k_period + 1: i + 1])
        l = min(lows[i - k_period + 1: i + 1])
        if h == l:
            k_values.append(50.0)
        else:
            k_values.append((closes[i] - l) / (h - l) * 100)

    d_values = sma([v if v is not None else 0 for v in k_values], d_period)

    return {"k": k_values, "d": d_values}


def volume_trend(volumes: list[float], period: int = 20) -> list[str | None]:
    """
    Analyse de tendance du volume.
    Retourne: 'HIGH' | 'NORMAL' | 'LOW' pour chaque point
    """
    result = [None] * (period - 1)
    for i in range(period - 1, len(volumes)):
        window = volumes[i - period + 1: i + 1]
        avg = sum(window) / period
        current = volumes[i]
        if current > avg * 1.5:
            result.append("HIGH")
        elif current < avg * 0.5:
            result.append("LOW")
        else:
            result.append("NORMAL")
    return result


def support_resistance(prices: list[float], window: int = 10) -> dict:
    """
    Détecte les niveaux de support et résistance locaux.
    Retourne: { 'supports': [prix], 'resistances': [prix] }
    """
    supports = []
    resistances = []

    for i in range(window, len(prices) - window):
        segment = prices[i - window: i + window + 1]
        low = min(segment)
        high = max(segment)
        if prices[i] == low:
            supports.append(prices[i])
        if prices[i] == high:
            resistances.append(prices[i])

    return {
        "supports":    sorted(list(set(round(s, 6) for s in supports))),
        "resistances": sorted(list(set(round(r, 6) for r in resistances))),
    }


def compute_all(candles: list[dict]) -> dict:
    """
    Calcule tous les indicateurs à partir d'une liste de bougies OHLCV.
    Candle format: { 'open', 'high', 'low', 'close', 'timestamp' }
    Retourne un dict complet avec tous les indicateurs.
    """
    if len(candles) < 30:
        return {}

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]

    rsi_values  = rsi(closes, 14)
    macd_values = macd(closes)
    bb_values   = bollinger_bands(closes, 20)
    atr_values  = atr(highs, lows, closes, 14)
    stoch       = stochastic(highs, lows, closes)
    sr          = support_resistance(closes)

    last = -1  # Index du dernier point

    def safe(lst):
        if not lst:
            return None
        val = lst[last]
        return val

    return {
        "rsi":              safe(rsi_values),
        "macd_line":        safe(macd_values["macd"]),
        "macd_signal":      safe(macd_values["signal"]),
        "macd_histogram":   safe(macd_values["histogram"]),
        "bb_upper":         safe(bb_values["upper"]),
        "bb_middle":        safe(bb_values["middle"]),
        "bb_lower":         safe(bb_values["lower"]),
        "bb_bandwidth":     safe(bb_values["bandwidth"]),
        "atr":              safe(atr_values),
        "stoch_k":          safe(stoch["k"]),
        "stoch_d":          safe(stoch["d"]),
        "ema_12":           safe(_ema(closes, 12)),
        "ema_26":           safe(_ema(closes, 26)),
        "ema_50":           safe(_ema(closes, 50)),
        "sma_20":           safe(sma(closes, 20)),
        "sma_50":           safe(sma(closes, 50)),
        "current_price":    closes[last],
        "supports":         sr["supports"][-3:] if sr["supports"] else [],
        "resistances":      sr["resistances"][-3:] if sr["resistances"] else [],
    }
