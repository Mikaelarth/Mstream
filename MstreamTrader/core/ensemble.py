"""
MstreamTrader - Ensemble Voting System
========================================

Au lieu d'UNE SEULE stratégie, le bot orchestre 3 sous-stratégies
INDÉPENDANTES qui votent pour chaque décision d'entrée :

  1. TREND FOLLOWER   : achète les coins en tendance haussière forte (MA crossover + ADX)
  2. MEAN REVERSION   : achète les coins survendus qui touchent un support (RSI extrême + BB)
  3. BREAKOUT HUNTER  : achète les cassures de résistance confirmées par le volume

Chaque stratégie émet un vote (-1, 0, +1) avec un niveau de confiance (0-100).
Le vote final combine :
    score_ensemble = Σ (vote × confidence × weight) / Σ weights

Règle : seuls les signaux avec ≥ 2 stratégies ACCORD + score > seuil sont validés.

Avantages institutionels :
    - Réduit massivement les faux signaux (1 stratégie peut se tromper, 3 rarement en même temps)
    - Diversifie le type d'alpha capturé (tendance + contrarian + breakout)
    - Plus robuste aux changements de régime (une stratégie qui sous-performe
      est compensée par les autres)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StrategyVote(Enum):
    STRONG_BUY  = 2
    BUY         = 1
    HOLD        = 0
    SELL        = -1
    STRONG_SELL = -2


@dataclass
class StrategyOpinion:
    """Avis d'une sous-stratégie."""
    strategy:   str
    vote:       StrategyVote
    confidence: float        # 0 à 100
    reasoning:  list = field(default_factory=list)


@dataclass
class EnsembleDecision:
    """Décision finale après vote."""
    coin_id:         str
    opinions:        list   # liste de StrategyOpinion
    final_vote:      StrategyVote
    ensemble_score:  float  # pondéré, -100 à +100
    agreement_count: int    # nb stratégies qui votent dans la même direction
    confidence:      float  # 0 à 100 (moyenne pondérée)
    reasoning:       list = field(default_factory=list)


# ─── Stratégies individuelles ─────────────────────────────────────────────────

def strategy_trend_follower(indicators_: dict) -> StrategyOpinion:
    """
    Trend Following : suit la tendance dominante via EMA + MACD.
    Philosophie : "the trend is your friend".
    """
    reasons = []
    score = 0
    price    = indicators_.get("current_price", 0)
    ema_12   = indicators_.get("ema_12")
    ema_26   = indicators_.get("ema_26")
    ema_50   = indicators_.get("ema_50")
    macd_l   = indicators_.get("macd_line")
    macd_s   = indicators_.get("macd_signal")
    macd_h   = indicators_.get("macd_histogram")

    # EMA alignment (12 > 26 > 50 en tendance haussière)
    if ema_12 and ema_26 and ema_50:
        if ema_12 > ema_26 > ema_50:
            score += 40
            reasons.append("EMA parfaitement alignee haussiere (12>26>50)")
        elif ema_12 < ema_26 < ema_50:
            score -= 40
            reasons.append("EMA parfaitement alignee baissiere (12<26<50)")
        elif ema_12 > ema_26:
            score += 15
            reasons.append("EMA 12>26 (tendance court terme haussiere)")
        else:
            score -= 15

    # Prix au-dessus EMA 50 (filtre tendance long)
    if price > 0 and ema_50:
        if price > ema_50 * 1.02:
            score += 15
            reasons.append("Prix > EMA50 +2% (trend long haussier fort)")
        elif price < ema_50 * 0.98:
            score -= 15

    # MACD momentum
    if macd_l is not None and macd_s is not None:
        if macd_l > macd_s and macd_l > 0:
            score += 20
            reasons.append("MACD positif et au-dessus signal (momentum haussier)")
        elif macd_l < macd_s and macd_l < 0:
            score -= 20
        if macd_h is not None:
            if macd_h > 0 and macd_l > macd_s:
                score += 10   # histogramme croissant
            elif macd_h < 0 and macd_l < macd_s:
                score -= 10

    # Translation en vote
    if   score >=  50: vote = StrategyVote.STRONG_BUY
    elif score >=  20: vote = StrategyVote.BUY
    elif score <= -50: vote = StrategyVote.STRONG_SELL
    elif score <= -20: vote = StrategyVote.SELL
    else:              vote = StrategyVote.HOLD

    return StrategyOpinion(
        strategy   = "trend_follower",
        vote       = vote,
        confidence = min(100, abs(score) * 1.2),
        reasoning  = reasons,
    )


def strategy_mean_reversion(indicators_: dict) -> StrategyOpinion:
    """
    Mean Reversion : achète le survendu, vend le surchauffé.
    Philosophie : "les extrêmes reviennent à la moyenne".
    """
    reasons = []
    score = 0
    rsi     = indicators_.get("rsi")
    price   = indicators_.get("current_price", 0)
    bb_up   = indicators_.get("bb_upper")
    bb_mid  = indicators_.get("bb_middle")
    bb_low  = indicators_.get("bb_lower")
    stoch_k = indicators_.get("stoch_k")
    stoch_d = indicators_.get("stoch_d")

    # RSI extrême
    if rsi is not None:
        if rsi < 25:
            score += 40
            reasons.append(f"RSI {rsi:.1f} survente extreme (achat mean reversion)")
        elif rsi < 35:
            score += 20
            reasons.append(f"RSI {rsi:.1f} survendu")
        elif rsi > 75:
            score -= 40
            reasons.append(f"RSI {rsi:.1f} surchauffe extreme")
        elif rsi > 65:
            score -= 20

    # Position dans Bollinger Bands
    if bb_up and bb_low and bb_mid and price > 0:
        bb_range = bb_up - bb_low
        if bb_range > 0:
            pos = (price - bb_low) / bb_range   # 0 = bande basse, 1 = bande haute
            if pos < 0.1:
                score += 30
                reasons.append("Prix colle BB basse (reversion probable)")
            elif pos > 0.9:
                score -= 30
                reasons.append("Prix colle BB haute (reversion probable)")

    # Stochastique extrême
    if stoch_k is not None and stoch_d is not None:
        if stoch_k < 15 and stoch_d < 15:
            score += 20
            reasons.append("Stochastique double survente")
        elif stoch_k > 85 and stoch_d > 85:
            score -= 20

    if   score >=  50: vote = StrategyVote.STRONG_BUY
    elif score >=  20: vote = StrategyVote.BUY
    elif score <= -50: vote = StrategyVote.STRONG_SELL
    elif score <= -20: vote = StrategyVote.SELL
    else:              vote = StrategyVote.HOLD

    return StrategyOpinion(
        strategy   = "mean_reversion",
        vote       = vote,
        confidence = min(100, abs(score) * 1.2),
        reasoning  = reasons,
    )


def strategy_breakout_hunter(indicators_: dict) -> StrategyOpinion:
    """
    Breakout Hunter : détecte les cassures de résistance / support.
    Philosophie : "buy high, sell higher" — achète les breakouts confirmés.
    """
    reasons = []
    score = 0
    price        = indicators_.get("current_price", 0)
    resistances  = indicators_.get("resistances", [])
    supports     = indicators_.get("supports", [])
    bb_bandwidth = indicators_.get("bb_bandwidth")
    atr          = indicators_.get("atr")

    # Breakout de résistance
    if resistances and price > 0:
        sorted_res = sorted(resistances, reverse=True)
        broken = [r for r in sorted_res if price > r * 1.001]
        if broken:
            nearest_broken = broken[0]
            margin_pct = (price - nearest_broken) / nearest_broken * 100
            if margin_pct < 3:   # breakout récent, pas trop étiré
                score += 35
                reasons.append(f"Cassure de resistance @ {nearest_broken:.4f} (+{margin_pct:.2f}%)")

    # Breakdown de support (bearish)
    if supports and price > 0:
        sorted_sup = sorted(supports)
        broken_down = [s for s in sorted_sup if price < s * 0.999]
        if broken_down:
            nearest_broken = broken_down[-1]
            margin_pct = (nearest_broken - price) / nearest_broken * 100
            if margin_pct < 3:
                score -= 35
                reasons.append(f"Cassure de support @ {nearest_broken:.4f} (-{margin_pct:.2f}%)")

    # Squeeze BB (volatilité compressed → explosion imminente)
    if bb_bandwidth is not None and bb_bandwidth < 4.0:
        score += 15   # bias haussier par défaut en squeeze (plus de squeezes résolvent up)
        reasons.append(f"Squeeze Bollinger ({bb_bandwidth:.2f}%) — volatilite imminente")

    # Confirmation par ATR élevé (momentum)
    if atr and price > 0:
        atr_pct = (atr / price) * 100
        if atr_pct > 3.0 and score > 0:
            score += 10
            reasons.append(f"ATR eleve ({atr_pct:.2f}%) confirme le momentum")

    if   score >=  50: vote = StrategyVote.STRONG_BUY
    elif score >=  20: vote = StrategyVote.BUY
    elif score <= -50: vote = StrategyVote.STRONG_SELL
    elif score <= -20: vote = StrategyVote.SELL
    else:              vote = StrategyVote.HOLD

    return StrategyOpinion(
        strategy   = "breakout_hunter",
        vote       = vote,
        confidence = min(100, abs(score) * 1.2),
        reasoning  = reasons,
    )


# ─── Voting ───────────────────────────────────────────────────────────────────

# Poids par stratégie (ajustables selon régime)
DEFAULT_WEIGHTS = {
    "trend_follower":  1.0,
    "mean_reversion":  0.9,
    "breakout_hunter": 0.8,
}

# Pondérations adaptées au régime de marché
REGIME_WEIGHTS = {
    "bull": {
        "trend_follower":  1.3,   # bull market = trend follower roi
        "mean_reversion":  0.6,   # reversion moins fiable (pullbacks rapides)
        "breakout_hunter": 1.0,
    },
    "bear": {
        "trend_follower":  0.4,   # bear market = trend follower piège
        "mean_reversion":  0.5,   # reversion risquée (falling knives)
        "breakout_hunter": 0.6,   # breakouts rares et peu fiables
    },
    "neutral": {
        "trend_follower":  0.8,
        "mean_reversion":  1.2,   # mean reversion brille en range
        "breakout_hunter": 1.0,
    },
}


def vote(coin_id: str, indicators_: dict, regime: str = "neutral",
          adaptive_weights: Optional[dict] = None) -> EnsembleDecision:
    """
    Soumet les indicateurs aux 3 stratégies et retourne la décision d'ensemble.

    Si `adaptive_weights` est fourni (depuis AdaptiveAgent.get_strategy_weights),
    il écrase les REGIME_WEIGHTS statiques — permet l'apprentissage en ligne.
    """
    # Priorité aux weights adaptatifs (Thompson Sampling) s'ils sont fournis
    weights = adaptive_weights if adaptive_weights else REGIME_WEIGHTS.get(regime, DEFAULT_WEIGHTS)

    opinions = [
        strategy_trend_follower(indicators_),
        strategy_mean_reversion(indicators_),
        strategy_breakout_hunter(indicators_),
    ]

    # Score pondéré
    total_weight = 0
    weighted_sum = 0
    weighted_conf = 0
    for op in opinions:
        w = weights.get(op.strategy, 1.0)
        # Vote × confidence × weight
        contribution = op.vote.value * (op.confidence / 100) * w
        weighted_sum  += contribution * 25   # mapper sur -100..+100
        weighted_conf += op.confidence * w
        total_weight  += w

    final_score = weighted_sum / total_weight if total_weight > 0 else 0
    avg_conf    = weighted_conf / total_weight if total_weight > 0 else 0

    # Vote final
    if   final_score >=  50: final_vote = StrategyVote.STRONG_BUY
    elif final_score >=  20: final_vote = StrategyVote.BUY
    elif final_score <= -50: final_vote = StrategyVote.STRONG_SELL
    elif final_score <= -20: final_vote = StrategyVote.SELL
    else:                    final_vote = StrategyVote.HOLD

    # Nombre de stratégies en accord (direction commune avec final_vote)
    if final_vote.value > 0:
        agreement = sum(1 for op in opinions if op.vote.value > 0)
    elif final_vote.value < 0:
        agreement = sum(1 for op in opinions if op.vote.value < 0)
    else:
        agreement = sum(1 for op in opinions if op.vote == StrategyVote.HOLD)

    reasoning = [f"[ENSEMBLE regime={regime}] Final score {final_score:+.1f} "
                 f"({agreement}/3 en accord)"]
    for op in opinions:
        reasoning.append(f"  - {op.strategy:15} : {op.vote.name:12} "
                         f"(conf {op.confidence:.0f}%)")

    return EnsembleDecision(
        coin_id         = coin_id,
        opinions        = opinions,
        final_vote      = final_vote,
        ensemble_score  = round(final_score, 2),
        agreement_count = agreement,
        confidence      = round(avg_conf, 2),
        reasoning       = reasoning,
    )


def is_ensemble_qualified(decision: EnsembleDecision,
                           min_agreement: int = 2,
                           min_score: float = 30.0,
                           min_confidence: float = 50.0) -> bool:
    """
    Vérifie qu'une décision d'ensemble passe les seuils de qualification.

    Défaut : au moins 2/3 stratégies d'accord, score ≥ 30, confiance ≥ 50 %.
    """
    if decision.final_vote not in (StrategyVote.BUY, StrategyVote.STRONG_BUY):
        return False
    if decision.agreement_count < min_agreement:
        return False
    if decision.ensemble_score < min_score:
        return False
    if decision.confidence < min_confidence:
        return False
    return True
