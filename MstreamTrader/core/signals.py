"""
MstreamTrader - Moteur de Signaux Trading
Analyse multi-indicateurs pour générer des signaux BUY / SELL / HOLD
avec score de confiance et explication détaillée.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Signal(Enum):
    STRONG_BUY  = "STRONG_BUY"
    BUY         = "BUY"
    HOLD        = "HOLD"
    SELL        = "SELL"
    STRONG_SELL = "STRONG_SELL"


SIGNAL_COLORS = {
    Signal.STRONG_BUY:  (0.0, 0.85, 0.4, 1),
    Signal.BUY:         (0.2, 0.75, 0.2, 1),
    Signal.HOLD:        (0.9, 0.75, 0.1, 1),
    Signal.SELL:        (0.9, 0.35, 0.1, 1),
    Signal.STRONG_SELL: (0.9, 0.1,  0.1, 1),
}

SIGNAL_LABELS = {
    Signal.STRONG_BUY:  "ACHAT FORT",
    Signal.BUY:         "ACHAT",
    Signal.HOLD:        "CONSERVER",
    Signal.SELL:        "VENTE",
    Signal.STRONG_SELL: "VENTE FORTE",
}


@dataclass
class TradeSignal:
    coin_id:    str
    symbol:     str
    signal:     Signal
    score:      float          # -100 à +100 (positif = haussier)
    confidence: float          # 0 à 100 %
    price:      float
    reasons:    list[str] = field(default_factory=list)
    stop_loss:  float = 0.0    # Prix stop-loss recommandé
    take_profit: float = 0.0   # Prix take-profit recommandé
    risk_reward: float = 0.0   # Ratio risque/récompense
    timestamp:  str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))

    @property
    def signal_label(self) -> str:
        return SIGNAL_LABELS[self.signal]

    @property
    def color(self) -> tuple:
        return SIGNAL_COLORS[self.signal]


def _score_rsi(rsi_val: float | None) -> tuple[float, list[str]]:
    """Évalue le RSI et retourne (score, raisons)."""
    if rsi_val is None:
        return 0, []
    reasons = []
    if rsi_val < 20:
        reasons.append(f"RSI {rsi_val:.1f} — Survente extrême (signal d'achat fort)")
        return 40, reasons
    elif rsi_val < 30:
        reasons.append(f"RSI {rsi_val:.1f} — Zone de survente (achat probable)")
        return 25, reasons
    elif rsi_val < 45:
        reasons.append(f"RSI {rsi_val:.1f} — Légère faiblesse")
        return 10, reasons
    elif rsi_val <= 55:
        reasons.append(f"RSI {rsi_val:.1f} — Zone neutre")
        return 0, reasons
    elif rsi_val <= 70:
        reasons.append(f"RSI {rsi_val:.1f} — Momentum haussier")
        return -10, reasons
    elif rsi_val <= 80:
        reasons.append(f"RSI {rsi_val:.1f} — Zone de surachat (prudence)")
        return -25, reasons
    else:
        reasons.append(f"RSI {rsi_val:.1f} — Surachat extrême (signal de vente fort)")
        return -40, reasons


def _score_macd(
    macd_line: float | None,
    macd_signal: float | None,
    histogram: float | None,
) -> tuple[float, list[str]]:
    if macd_line is None or macd_signal is None:
        return 0, []
    reasons = []
    score = 0

    if macd_line > macd_signal:
        if histogram and histogram > 0 and histogram > abs(macd_line) * 0.05:
            reasons.append("MACD au-dessus du signal et croissant — Momentum haussier fort")
            score += 20
        else:
            reasons.append("MACD au-dessus du signal — Tendance haussière")
            score += 10
    else:
        if histogram and histogram < 0 and abs(histogram) > abs(macd_line) * 0.05:
            reasons.append("MACD sous le signal et décroissant — Momentum baissier fort")
            score -= 20
        else:
            reasons.append("MACD sous le signal — Tendance baissière")
            score -= 10

    if macd_line > 0:
        reasons.append("MACD positif — Au-dessus de la ligne zéro (haussier)")
        score += 5
    else:
        reasons.append("MACD négatif — Sous la ligne zéro (baissier)")
        score -= 5

    return score, reasons


def _score_bollinger(
    price: float,
    bb_upper: float | None,
    bb_middle: float | None,
    bb_lower: float | None,
    bandwidth: float | None,
) -> tuple[float, list[str]]:
    if None in (bb_upper, bb_middle, bb_lower):
        return 0, []
    reasons = []
    score = 0

    bb_range = bb_upper - bb_lower
    if bb_range == 0:
        return 0, []

    position = (price - bb_lower) / bb_range  # 0 = bande basse, 1 = bande haute

    if price <= bb_lower:
        reasons.append(f"Prix sur la bande Bollinger inférieure — Support fort (achat)")
        score += 25
    elif position < 0.2:
        reasons.append(f"Prix proche bande Bollinger basse — Zone d'achat")
        score += 15
    elif position > 0.8:
        reasons.append(f"Prix proche bande Bollinger haute — Zone de résistance")
        score -= 15
    elif price >= bb_upper:
        reasons.append(f"Prix sur la bande Bollinger supérieure — Résistance forte (vente)")
        score -= 25

    if bandwidth and bandwidth < 5:
        reasons.append(f"Squeeze Bollinger ({bandwidth:.1f}%) — Explosion de volatilité imminente")
        score += 5 if position < 0.5 else -5

    return score, reasons


def _score_stochastic(
    k: float | None,
    d: float | None,
) -> tuple[float, list[str]]:
    if k is None or d is None:
        return 0, []
    reasons = []
    score = 0

    if k < 20 and d < 20:
        reasons.append(f"Stochastique %K={k:.1f} %D={d:.1f} — Double survente (achat fort)")
        score += 20
    elif k < 20:
        reasons.append(f"Stochastique %K={k:.1f} — Survente")
        score += 12
    elif k > 80 and d > 80:
        reasons.append(f"Stochastique %K={k:.1f} %D={d:.1f} — Double surachat (vente)")
        score -= 20
    elif k > 80:
        reasons.append(f"Stochastique %K={k:.1f} — Surachat")
        score -= 12

    if k > d and k < 80:
        reasons.append("Croisement haussier Stochastique")
        score += 8
    elif k < d and k > 20:
        reasons.append("Croisement baissier Stochastique")
        score -= 8

    return score, reasons


def _score_ema(
    price: float,
    ema_12: float | None,
    ema_26: float | None,
    ema_50: float | None,
) -> tuple[float, list[str]]:
    reasons = []
    score = 0

    if ema_12 and ema_26:
        if ema_12 > ema_26:
            reasons.append("EMA 12 > EMA 26 — Golden Cross (haussier)")
            score += 15
        else:
            reasons.append("EMA 12 < EMA 26 — Death Cross (baissier)")
            score -= 15

    if ema_50:
        if price > ema_50:
            reasons.append(f"Prix au-dessus EMA50 — Tendance long terme haussière")
            score += 10
        else:
            reasons.append(f"Prix sous EMA50 — Tendance long terme baissière")
            score -= 10

    return score, reasons


def _compute_stop_take(
    price: float,
    signal: Signal,
    atr_val: float | None,
    supports: list,
    resistances: list,
    min_rr: float = 2.0,
) -> tuple[float, float, float]:
    """
    Calcule stop-loss, take-profit et ratio risque/récompense (R/R).

    Règles de qualité (un trader pro ne prend pas de R/R < 2:1) :
      1. SL = max(1.5 × ATR, support * 0.995) — mais le support n'est utilisé
         QUE s'il est suffisamment éloigné (≥ 0.5 × ATR du prix). Sinon le
         marché est en consolidation et on prend le SL ATR.
      2. TP = price + 3 × ATR par défaut. La résistance plafonne SEULEMENT
         si elle est suffisamment éloignée (≥ 1 × ATR du prix). Sinon on
         garde l'ATR pure.
      3. Si malgré ça le R/R < min_rr, on étend le TP pour atteindre min_rr
         (le SL reste fixe — défini par la volatilité, intouchable).

    Retourne (stop_loss, take_profit, rr_ratio).
    """
    if atr_val is None or atr_val == 0:
        atr_val = price * 0.02  # 2% par défaut

    stop_loss = 0.0
    take_profit = 0.0

    if signal in (Signal.BUY, Signal.STRONG_BUY):
        # SL ATR-based (ancrage à la volatilité)
        stop_loss = price - (1.5 * atr_val)
        # Support seulement s'il est éloigné (sinon = consolidation = trap)
        if supports:
            valid_sup = [s for s in supports
                         if s < price and (price - s) >= 0.5 * atr_val]
            if valid_sup:
                nearest_support = max(valid_sup)
                # Le SL doit ÊTRE PLUS BAS que le support (sécurité)
                stop_loss = max(stop_loss, nearest_support * 0.995)

        # TP ATR par défaut (3× ATR = R/R 2:1 garanti)
        tp_atr = price + (3 * atr_val)
        if resistances:
            valid_res = [r for r in resistances
                         if r > price and (r - price) >= 1.0 * atr_val]
            if valid_res:
                nearest_resistance = min(valid_res)
                take_profit = min(tp_atr, nearest_resistance * 1.005)
            else:
                take_profit = tp_atr
        else:
            take_profit = tp_atr

        # Garantie R/R : si le R/R calculé est < min_rr, on étend le TP
        # SL reste fixe (intouchable, défini par la volatilité réelle)
        risk = price - stop_loss
        if risk > 0:
            current_rr = (take_profit - price) / risk
            if current_rr < min_rr:
                take_profit = price + risk * min_rr

    elif signal in (Signal.SELL, Signal.STRONG_SELL):
        stop_loss   = price + (1.5 * atr_val)
        take_profit = price - (3 * atr_val)
        if supports:
            valid_sup = [s for s in supports
                         if s < price and (price - s) >= 1.0 * atr_val]
            if valid_sup:
                nearest_support = max(valid_sup)
                take_profit = max(take_profit, nearest_support * 0.99)

        # Garantie R/R sur SELL aussi
        risk = stop_loss - price
        if risk > 0:
            current_rr = (price - take_profit) / risk
            if current_rr < min_rr:
                take_profit = price - risk * min_rr

    risk = abs(price - stop_loss)
    reward = abs(take_profit - price)
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0

    return round(stop_loss, 6), round(take_profit, 6), rr_ratio


def analyze(coin_id: str, symbol: str, indicators: dict) -> TradeSignal:
    """
    Analyse complète multi-indicateurs.
    Génère un signal de trading avec score de confiance.
    """
    price = indicators.get("current_price", 0)
    if price == 0:
        return TradeSignal(coin_id, symbol, Signal.HOLD, 0, 0, 0,
                           ["Données insuffisantes"])

    total_score = 0
    all_reasons = []

    # 1. RSI (poids: 25%)
    s, r = _score_rsi(indicators.get("rsi"))
    total_score += s * 1.0
    all_reasons.extend(r)

    # 2. MACD (poids: 25%)
    s, r = _score_macd(
        indicators.get("macd_line"),
        indicators.get("macd_signal"),
        indicators.get("macd_histogram"),
    )
    total_score += s * 1.0
    all_reasons.extend(r)

    # 3. Bollinger Bands (poids: 20%)
    s, r = _score_bollinger(
        price,
        indicators.get("bb_upper"),
        indicators.get("bb_middle"),
        indicators.get("bb_lower"),
        indicators.get("bb_bandwidth"),
    )
    total_score += s * 0.85
    all_reasons.extend(r)

    # 4. Stochastique (poids: 15%)
    s, r = _score_stochastic(
        indicators.get("stoch_k"),
        indicators.get("stoch_d"),
    )
    total_score += s * 0.75
    all_reasons.extend(r)

    # 5. EMA (poids: 15%)
    s, r = _score_ema(
        price,
        indicators.get("ema_12"),
        indicators.get("ema_26"),
        indicators.get("ema_50"),
    )
    total_score += s * 0.75
    all_reasons.extend(r)

    # Déterminer le signal selon le score
    score_clamped = max(-100, min(100, total_score))

    if score_clamped >= 50:
        signal = Signal.STRONG_BUY
    elif score_clamped >= 20:
        signal = Signal.BUY
    elif score_clamped <= -50:
        signal = Signal.STRONG_SELL
    elif score_clamped <= -20:
        signal = Signal.SELL
    else:
        signal = Signal.HOLD

    confidence = min(100, abs(score_clamped) * 1.2)

    # Calcul stop-loss / take-profit (R/R minimum garanti à 2.0)
    stop_loss, take_profit, rr_ratio = _compute_stop_take(
        price,
        signal,
        indicators.get("atr"),
        indicators.get("supports", []),
        indicators.get("resistances", []),
        min_rr=2.0,
    )

    # Garde-fou final : si malgré tout le R/R est faible (<1.5), on
    # dégrade le signal — on ne dit JAMAIS "ACHAT FORT" sur un trade
    # à espérance négative.
    if rr_ratio < 1.5 and signal in (Signal.STRONG_BUY, Signal.BUY):
        signal = Signal.HOLD
        all_reasons.insert(0, f"R/R trop faible ({rr_ratio:.2f}x) — signal converti en HOLD")
    elif rr_ratio < 1.5 and signal in (Signal.STRONG_SELL, Signal.SELL):
        signal = Signal.HOLD
        all_reasons.insert(0, f"R/R trop faible ({rr_ratio:.2f}x) — signal converti en HOLD")

    return TradeSignal(
        coin_id=coin_id,
        symbol=symbol,
        signal=signal,
        score=round(score_clamped, 1),
        confidence=round(confidence, 1),
        price=price,
        reasons=all_reasons,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=rr_ratio,
    )


def rank_opportunities(signals: list[TradeSignal]) -> list[TradeSignal]:
    """
    Trie les opportunités par score de confiance décroissant.
    Priorité aux BUY forts avec bon ratio R/R.
    """
    def sort_key(ts: TradeSignal):
        direction = 1 if ts.signal in (Signal.BUY, Signal.STRONG_BUY) else -1
        rr_bonus = ts.risk_reward * 5 if ts.risk_reward >= 2 else 0
        return direction * ts.confidence + rr_bonus

    return sorted(signals, key=sort_key, reverse=True)
