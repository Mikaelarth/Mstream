"""
MstreamTrader - Détecteur de Régime de Marché
==============================================

Le marché crypto alterne entre trois régimes fondamentaux :

  BULL     : tendance haussière établie → signaux BUY fiables
  BEAR     : tendance baissière établie → signaux BUY souvent des "falling knives"
  NEUTRAL  : range/transition → faux signaux dans les deux sens

Sans ce filtre, un bot qui applique les mêmes règles en toute condition
se fait laminer en bear market. Avec ce filtre, les seuils s'adaptent
au contexte macro.

Méthode : position de BTC par rapport à son EMA 200 daily
    +2 % au-dessus → BULL
    −2 % au-dessous → BEAR
    Entre les deux → NEUTRAL

Pourquoi BTC ? Les altcoins sont corrélés à BTC à 80-95 %. Le régime de BTC
définit le régime du marché crypto dans son ensemble.

Pourquoi EMA 200 ? C'est la moyenne mobile institutionnelle de référence
(équivalent crypto de la MM 200 sur actions). Utilisée par la majorité
des traders pros comme niveau de bascule bull/bear.
"""

from enum import Enum
from typing import Optional

from core.indicators import _ema


class Regime(Enum):
    BULL    = "bull"
    BEAR    = "bear"
    NEUTRAL = "neutral"


REGIME_LABELS = {
    Regime.BULL:    "Marché Haussier",
    Regime.BEAR:    "Marché Baissier",
    Regime.NEUTRAL: "Marché Neutre / Transition",
}


# Profils adaptatifs par régime : overrides sur les paramètres du Bot Maître
# Ces valeurs sont issues du principe "be strict when uncertain, loose when confident"
REGIME_PROFILES = {
    Regime.BULL: {
        # Régime favorable : tolérer plus de trades
        "min_score":      55.0,
        "min_confidence": 65.0,
        "min_rr":         2.5,
        "risk_pct":       5.0,
        "max_positions":  4,
        "max_capital_pct": 80.0,
    },
    Regime.NEUTRAL: {
        # Incertitude : durcir les critères, réduire l'exposition
        "min_score":      60.0,
        "min_confidence": 70.0,
        "min_rr":         3.0,
        "risk_pct":       3.5,
        "max_positions":  3,
        "max_capital_pct": 60.0,
    },
    Regime.BEAR: {
        # Hostile aux BUY : très strict, petit risque, peu de positions
        "min_score":      70.0,
        "min_confidence": 75.0,
        "min_rr":         3.5,
        "risk_pct":       2.0,
        "max_positions":  2,
        "max_capital_pct": 40.0,
    },
}


def detect_regime(
    btc_daily_closes: list[float],
    ema_period: int = 200,
    threshold_pct: float = 2.0,
) -> tuple[Regime, Optional[float]]:
    """
    Détecte le régime du marché à partir des clôtures daily BTC.

    Args:
        btc_daily_closes: liste de prix de clôture daily BTC (du plus ancien au plus récent)
        ema_period:       période de l'EMA (défaut 200)
        threshold_pct:    seuil de bascule en % (défaut ±2 %)

    Returns:
        (régime, écart_pct) — écart = (prix − EMA) / EMA × 100
        écart None si données insuffisantes.

    Fallback : NEUTRAL si moins de `ema_period` bougies (données insuffisantes).
    """
    if not btc_daily_closes or len(btc_daily_closes) < ema_period:
        return Regime.NEUTRAL, None

    ema_values = _ema(btc_daily_closes, ema_period)
    current_price = btc_daily_closes[-1]
    current_ema   = ema_values[-1]

    if current_ema is None or current_ema <= 0:
        return Regime.NEUTRAL, None

    deviation_pct = (current_price - current_ema) / current_ema * 100

    if deviation_pct > threshold_pct:
        return Regime.BULL, deviation_pct
    if deviation_pct < -threshold_pct:
        return Regime.BEAR, deviation_pct
    return Regime.NEUTRAL, deviation_pct


def detect_regime_from_candles(
    btc_daily_candles: list[dict],
    ema_period: int = 200,
    threshold_pct: float = 2.0,
) -> tuple[Regime, Optional[float]]:
    """Variante acceptant une liste de bougies OHLC (avec champ 'close')."""
    if not btc_daily_candles:
        return Regime.NEUTRAL, None
    closes = [c.get("close", 0) for c in btc_daily_candles if c.get("close", 0) > 0]
    return detect_regime(closes, ema_period, threshold_pct)


def get_profile(regime: Regime) -> dict:
    """Retourne les paramètres adaptés au régime donné."""
    return REGIME_PROFILES.get(regime, REGIME_PROFILES[Regime.NEUTRAL]).copy()


def describe(regime: Regime, deviation_pct: Optional[float] = None) -> str:
    """Description lisible du régime courant."""
    label = REGIME_LABELS.get(regime, str(regime.value))
    if deviation_pct is None:
        return label
    sign = "+" if deviation_pct >= 0 else ""
    return f"{label} (BTC {sign}{deviation_pct:.2f}% vs EMA 200)"


# ─── Détection de transition (signal avancé) ──────────────────────────────────

def detect_regime_transition(
    btc_daily_closes: list[float],
    lookback_days: int = 10,
) -> dict:
    """
    Détecte si une TRANSITION de régime est imminente — signal AVANCÉ.

    Méthode : analyser la vitesse de convergence entre prix et EMA 200.
    Si le prix se rapproche rapidement de la frontière (±2%), une bascule
    est probable dans les prochains jours.

    Signaux détectés :
      - EMA 50 croise EMA 200 vers le haut (golden cross) → transition vers BULL
      - EMA 50 croise EMA 200 vers le bas (death cross) → transition vers BEAR
      - Prix franchit EMA 200 avec momentum fort → bascule imminente
      - Rolling slope de EMA 200 qui s'inverse → trend long-terme qui change

    Retourne un dict avec :
        {
            "transitioning":     bool,
            "from_regime":       str,   # régime actuel
            "to_regime":         str,   # régime probable
            "transition_score":  float, # 0 à 1 (0 = stable, 1 = transition imminente)
            "signals":           list[str],
            "days_to_bascule":   int or None,   # estimation si calculable
        }
    """
    from core.indicators import _ema

    if not btc_daily_closes or len(btc_daily_closes) < 200:
        return {
            "transitioning":    False,
            "from_regime":      "unknown",
            "to_regime":        "unknown",
            "transition_score": 0.0,
            "signals":          ["Donnees insuffisantes (< 200 jours)"],
            "days_to_bascule":  None,
        }

    ema_50  = _ema(btc_daily_closes, 50)
    ema_200 = _ema(btc_daily_closes, 200)

    current_price = btc_daily_closes[-1]
    current_50    = ema_50[-1]
    current_200   = ema_200[-1]

    if current_200 is None or current_50 is None:
        return {
            "transitioning":    False,
            "from_regime":      "unknown",
            "to_regime":        "unknown",
            "transition_score": 0.0,
            "signals":          ["EMA non calculable"],
            "days_to_bascule":  None,
        }

    signals_detected = []
    score = 0.0
    from_regime, _ = detect_regime(btc_daily_closes)
    to_regime = from_regime   # par défaut, pas de transition

    # 1. Détection golden cross / death cross (EMA 50 vs EMA 200)
    # Regarder la dernière intersection dans la lookback window
    cross_detected = None
    if len(ema_50) >= lookback_days + 1 and len(ema_200) >= lookback_days + 1:
        for i in range(len(ema_50) - lookback_days, len(ema_50)):
            if ema_50[i - 1] is None or ema_200[i - 1] is None:
                continue
            if ema_50[i] is None or ema_200[i] is None:
                continue
            # Croisement ?
            prev_diff = ema_50[i - 1] - ema_200[i - 1]
            curr_diff = ema_50[i]     - ema_200[i]
            if prev_diff < 0 and curr_diff > 0:
                cross_detected = "golden"
                days_ago = len(ema_50) - 1 - i
                signals_detected.append(f"Golden Cross (EMA50>EMA200) il y a {days_ago}j")
                score += 0.4
            elif prev_diff > 0 and curr_diff < 0:
                cross_detected = "death"
                days_ago = len(ema_50) - 1 - i
                signals_detected.append(f"Death Cross (EMA50<EMA200) il y a {days_ago}j")
                score += 0.4

    if cross_detected == "golden" and from_regime != Regime.BULL:
        to_regime = Regime.BULL
    elif cross_detected == "death" and from_regime != Regime.BEAR:
        to_regime = Regime.BEAR

    # 2. Prix qui franchit EMA 200 avec momentum
    dev_current = (current_price - current_200) / current_200 * 100
    if len(btc_daily_closes) >= lookback_days + 1:
        dev_lookback = ((btc_daily_closes[-(lookback_days + 1)] - current_200) / current_200 * 100)
        dev_delta = dev_current - dev_lookback
        # Si le prix s'est éloigné de l'EMA200 de + de 5 % sur la période = momentum fort
        if abs(dev_delta) > 5.0:
            if dev_delta > 0:
                signals_detected.append(
                    f"Momentum haussier : prix gagne {dev_delta:+.2f}% vs EMA200 en {lookback_days}j"
                )
                score += 0.3
                if from_regime != Regime.BULL:
                    to_regime = Regime.BULL
            else:
                signals_detected.append(
                    f"Momentum baissier : prix perd {dev_delta:.2f}% vs EMA200 en {lookback_days}j"
                )
                score += 0.3
                if from_regime != Regime.BEAR:
                    to_regime = Regime.BEAR

    # 3. Slope de l'EMA 200 qui s'inverse (trend long-terme)
    if len(ema_200) >= lookback_days + 1:
        prev_200 = ema_200[-(lookback_days + 1)]
        if prev_200 is not None:
            slope_pct = (current_200 - prev_200) / prev_200 * 100
            # Si EMA 200 elle-même se retourne, c'est un signal fort
            if abs(slope_pct) > 2.0:
                if slope_pct > 0:
                    signals_detected.append(f"EMA 200 en hausse ({slope_pct:+.2f}% sur {lookback_days}j)")
                    if from_regime == Regime.BEAR:
                        score += 0.2
                        to_regime = Regime.NEUTRAL
                else:
                    signals_detected.append(f"EMA 200 en baisse ({slope_pct:.2f}% sur {lookback_days}j)")
                    if from_regime == Regime.BULL:
                        score += 0.2
                        to_regime = Regime.NEUTRAL

    # 4. Prix proche de la frontière ±2 % (zone de bascule imminente)
    if abs(dev_current) < 3.0 and from_regime == Regime.NEUTRAL:
        # On est en neutral et prix proche EMA → bascule imminente dans un sens
        signals_detected.append(f"Prix proche frontiere ({dev_current:+.2f}% vs EMA200)")
        score += 0.1

    transitioning = score >= 0.3 and to_regime != from_regime

    # Estimation jours avant bascule (heuristique : basée sur la vitesse du delta)
    days_to = None
    if transitioning and abs(dev_current) < 2.0 and len(btc_daily_closes) >= 5:
        recent_slope = (btc_daily_closes[-1] - btc_daily_closes[-5]) / 5
        if recent_slope != 0:
            # Distance en prix jusqu'à la frontière
            if to_regime == Regime.BULL:
                target_price = current_200 * 1.02
            elif to_regime == Regime.BEAR:
                target_price = current_200 * 0.98
            else:
                target_price = current_200
            distance = target_price - current_price
            if recent_slope != 0:
                days_est = distance / recent_slope
                if 0 < days_est < 30:
                    days_to = int(abs(days_est))

    return {
        "transitioning":     transitioning,
        "from_regime":       from_regime.value,
        "to_regime":         to_regime.value if isinstance(to_regime, Regime) else to_regime,
        "transition_score":  round(min(score, 1.0), 3),
        "signals":           signals_detected,
        "days_to_bascule":   days_to,
        "btc_deviation_pct": round(dev_current, 3),
    }
