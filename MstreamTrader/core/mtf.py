"""
MstreamTrader - Multi-Timeframe Confluence (MTF)
=================================================

Technique STANDARD chez les traders pros : ne pas prendre un trade basé sur
UN SEUL timeframe. Exiger la CONFLUENCE de plusieurs horizons temporels.

Principe :
    Timeframe long  (daily)  → définit la TENDANCE de fond
    Timeframe moyen (4h)     → définit le MOMENTUM
    Timeframe court (1h)     → définit le TIMING d'entrée

Règle d'or : ne trader que dans le sens de la tendance du TF supérieur.
    Daily bullish + 4h bullish + 1h signal d'achat = trade qualifié
    Daily bearish + 4h bullish + 1h signal d'achat = PIÈGE, refuser

Ce module calcule un score de confluence MTF (0 à 3) qui exprime combien
de timeframes s'alignent. Seuls les signaux avec confluence ≥ 2/3 sont
considérés valides par le bot.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TimeframeSignal:
    """Signal pour un seul timeframe."""
    timeframe:    str      # "1h" | "4h" | "1d"
    direction:    int      # +1 bullish | 0 neutre | -1 bearish
    strength:     float    # 0 à 100 (équivalent score)
    rsi:          Optional[float] = None
    macd_bullish: bool = False
    ema_bullish:  bool = False   # EMA 12 > EMA 26
    reasons:      list = field(default_factory=list)


@dataclass
class MTFConfluence:
    """Résultat de l'analyse multi-timeframe."""
    coin_id:          str
    timeframes:       dict[str, TimeframeSignal] = field(default_factory=dict)
    confluence_score: int   = 0    # nombre de TF alignés bullish (0 à N)
    total_timeframes: int   = 0
    is_bullish_aligned: bool = False
    is_bearish_aligned: bool = False
    dominant_direction: int  = 0
    reasoning:        list  = field(default_factory=list)


# ─── Calcul direction d'un timeframe ──────────────────────────────────────────

def compute_single_timeframe(candles: list[dict], timeframe: str) -> TimeframeSignal:
    """
    Analyse un single timeframe et retourne sa direction + force.
    Logique simplifiée : EMA, RSI, MACD → vote global.
    """
    from core import indicators as ind

    if not candles or len(candles) < 30:
        return TimeframeSignal(timeframe=timeframe, direction=0, strength=0.0,
                               reasons=["Donnees insuffisantes"])

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]

    direction = 0
    strength_votes = []
    reasons = []

    # EMA 12 vs 26
    ema_12 = ind._ema(closes, 12)
    ema_26 = ind._ema(closes, 26)
    if ema_12 and ema_26 and ema_12[-1] is not None and ema_26[-1] is not None:
        ema_bullish = ema_12[-1] > ema_26[-1]
        direction += 1 if ema_bullish else -1
        strength_votes.append(25 if ema_bullish else -25)
        reasons.append(f"[{timeframe}] EMA 12{'>'if ema_bullish else'<'}26")
    else:
        ema_bullish = False

    # RSI
    rsi_vals = ind.rsi(closes, 14)
    rsi_val = None
    if rsi_vals:
        rsi_val = rsi_vals[-1]
        if rsi_val is not None:
            if rsi_val > 55:
                direction += 1
                strength_votes.append(20)
                reasons.append(f"[{timeframe}] RSI {rsi_val:.1f} bullish")
            elif rsi_val < 45:
                direction -= 1
                strength_votes.append(-20)
                reasons.append(f"[{timeframe}] RSI {rsi_val:.1f} bearish")

    # MACD
    macd_data = ind.macd(closes)
    macd_bullish = False
    if macd_data and macd_data["macd"][-1] is not None and macd_data["signal"][-1] is not None:
        macd_bullish = macd_data["macd"][-1] > macd_data["signal"][-1]
        direction += 1 if macd_bullish else -1
        strength_votes.append(25 if macd_bullish else -25)
        reasons.append(f"[{timeframe}] MACD {'>'if macd_bullish else'<'} signal")

    # Trend par EMA 50 long terme
    if len(closes) >= 50:
        ema_50 = ind._ema(closes, 50)
        if ema_50 and ema_50[-1] is not None:
            price = closes[-1]
            long_bullish = price > ema_50[-1]
            direction += 1 if long_bullish else -1
            strength_votes.append(15 if long_bullish else -15)
            reasons.append(f"[{timeframe}] Prix {'>'if long_bullish else'<'}EMA50")

    # Direction finale
    final_direction = 0
    if direction > 0:
        final_direction = 1
    elif direction < 0:
        final_direction = -1

    avg_strength = abs(sum(strength_votes) / len(strength_votes)) if strength_votes else 0

    return TimeframeSignal(
        timeframe    = timeframe,
        direction    = final_direction,
        strength     = avg_strength,
        rsi          = rsi_val,
        macd_bullish = macd_bullish,
        ema_bullish  = ema_bullish,
        reasons      = reasons,
    )


# ─── Confluence ───────────────────────────────────────────────────────────────

def analyze_confluence(coin_id: str,
                        candles_by_tf: dict) -> MTFConfluence:
    """
    Analyse la confluence multi-timeframe.

    Args:
        coin_id       : identifiant du coin
        candles_by_tf : dict[timeframe_str → list[candles]]
            ex: {"1h": [...], "4h": [...], "1d": [...]}

    Retourne un MTFConfluence avec le score et la direction.
    """
    result = MTFConfluence(coin_id=coin_id)

    bullish_count = 0
    bearish_count = 0

    for tf, candles in candles_by_tf.items():
        tf_sig = compute_single_timeframe(candles, tf)
        result.timeframes[tf] = tf_sig
        result.reasoning.extend(tf_sig.reasons)

        if tf_sig.direction > 0:
            bullish_count += 1
        elif tf_sig.direction < 0:
            bearish_count += 1

    result.total_timeframes = len(candles_by_tf)

    # Direction dominante
    if bullish_count > bearish_count:
        result.dominant_direction = 1
        result.confluence_score = bullish_count
    elif bearish_count > bullish_count:
        result.dominant_direction = -1
        result.confluence_score = bearish_count
    else:
        result.dominant_direction = 0
        result.confluence_score = 0

    # Alignement requis : au moins 2/3 des timeframes
    min_alignment = max(2, (result.total_timeframes * 2) // 3)
    result.is_bullish_aligned = (bullish_count >= min_alignment)
    result.is_bearish_aligned = (bearish_count >= min_alignment)

    return result


def is_confluence_valid_for_long(confluence: MTFConfluence,
                                   min_confluence: int = 2) -> bool:
    """
    Vérifie qu'une entrée BUY est cohérente avec la confluence MTF.

    Règle :
        - Au moins `min_confluence` timeframes doivent être bullish
        - Aucun timeframe long-terme ne doit être clairement bearish
    """
    if confluence.confluence_score < min_confluence:
        return False
    if confluence.dominant_direction != 1:
        return False

    # Le TF le plus long ne doit PAS être strongly bearish
    tf_priority = ["1d", "4h", "1h"]   # du plus long au plus court
    for tf in tf_priority:
        if tf in confluence.timeframes:
            tf_sig = confluence.timeframes[tf]
            # Si le TF le plus long est bearish, refuser
            if tf_sig.direction < 0 and tf_sig.strength > 30:
                return False
            break   # on vérifie juste le plus long dispo

    return True


def describe_confluence(confluence: MTFConfluence) -> str:
    """Description lisible."""
    summary = f"MTF {confluence.coin_id} : "
    for tf, sig in confluence.timeframes.items():
        label = "bull" if sig.direction > 0 else ("bear" if sig.direction < 0 else "neutral")
        summary += f"{tf}={label}({sig.strength:.0f}) "
    if confluence.is_bullish_aligned:
        summary += f"[ALIGNE HAUSSIER {confluence.confluence_score}/{confluence.total_timeframes}]"
    elif confluence.is_bearish_aligned:
        summary += f"[ALIGNE BAISSIER {confluence.confluence_score}/{confluence.total_timeframes}]"
    else:
        summary += "[NON ALIGNE]"
    return summary
