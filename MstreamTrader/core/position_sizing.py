"""
MstreamTrader - Position Sizing Avancé
========================================

Algorithmes de dimensionnement niveau institutional :

  1. Kelly Criterion Fractional
     Formule mathématique optimale pour maximiser la croissance long-terme
     d'un capital soumis à des paris favorables répétés.

     f* = (p × b − q) / b
       p : probabilité de gain (win rate)
       q : probabilité de perte (1 − p)
       b : ratio gain moyen / perte moyenne

     On utilise FRACTIONAL Kelly (1/4 du full Kelly) — standard dans les
     hedge funds pour réduire la variance du capital.

  2. Volatility Targeting
     Ajuste la taille de position selon la volatilité réalisée du marché.
     Marché calme → positions plus grosses. Marché volatile → positions plus petites.

     size ≈ (target_vol / realized_vol) × base_size

  3. Combined Optimal Sizing
     Combine Kelly + Volatility targeting + plafond de risque absolu.
     Retourne le MINIMUM des trois → protection contre sur-exposition.

Références :
    - Kelly (1956) "A New Interpretation of Information Rate"
    - Thorp (1969) "Optimal Gambling Systems for Favorable Games"
    - Ed Thorp "The Kelly Capital Growth Investment Criterion" (2011)
"""

import sqlite3
from typing import Optional


# ─── Kelly Criterion ──────────────────────────────────────────────────────────

def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Calcule la fraction de Kelly FULL (0 à 1).

    Args:
        win_rate : probabilité de gain (0 à 1)
        avg_win  : gain moyen en USDT (positif)
        avg_loss : perte moyenne en USDT (positif — valeur absolue)

    Retourne la fraction recommandée du capital à parier.
    0 ou négatif = ne pas parier (pari défavorable).

    Exemple : 60% win rate, gain moyen $20, perte moyenne $10
        b = 20/10 = 2.0
        f* = (0.6 × 2.0 − 0.4) / 2.0 = 0.4 → 40% du capital
        (Full Kelly — bien trop agressif en pratique, d'où le Fractional)
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    b = avg_win / avg_loss
    if b <= 0:
        return 0.0
    q = 1 - win_rate
    f = (win_rate * b - q) / b
    return max(0.0, min(f, 1.0))


def fractional_kelly(win_rate: float, avg_win: float, avg_loss: float,
                      fraction: float = 0.25) -> float:
    """
    Kelly FRACTIONAL — fraction × full_kelly.

    Standard hedge fund : 1/4 Kelly (fraction=0.25).
    Pourquoi ? Kelly complet est théoriquement optimal mais suppose des paramètres
    connus avec certitude. En pratique win_rate/avg_win/avg_loss sont estimés
    avec erreur — le fractional couvre cette incertitude.

    Comparaison des fractions :
        1.00 (full Kelly)     : max growth mais 50%+ drawdown fréquents
        0.50 (half Kelly)     : 75% du growth, DD nettement réduit
        0.25 (quarter Kelly)  : standard retail prudent
        0.10 (1/10 Kelly)     : ultra-défensif, sub-optimal
    """
    f_full = kelly_fraction(win_rate, avg_win, avg_loss)
    return f_full * fraction


# ─── Volatility Targeting ─────────────────────────────────────────────────────

def volatility_target_multiplier(realized_vol_pct: float,
                                  target_vol_pct: float = 2.0,
                                  max_multiplier: float = 2.0,
                                  min_multiplier: float = 0.25) -> float:
    """
    Multiplicateur de position basé sur la volatilité réalisée.

    Args:
        realized_vol_pct : volatilité observée (ex: ATR / prix × 100)
        target_vol_pct   : volatilité cible (ex: 2% — niveau "normal" crypto)
        max_multiplier   : cap à la hausse (évite sur-exposition en période calme)
        min_multiplier   : floor à la baisse (garde un minimum de positions)

    Exemple :
        Marché calme : ATR=1% prix, target=2% → multiplier = 2× (positions plus grosses)
        Marché volatile : ATR=4% prix, target=2% → multiplier = 0.5× (positions réduites)
    """
    if realized_vol_pct <= 0:
        return 1.0
    mult = target_vol_pct / realized_vol_pct
    return max(min_multiplier, min(mult, max_multiplier))


# ─── Combined Sizing (le truc qui fait la différence) ─────────────────────────

def optimal_position_size(
    capital:             float,
    win_rate:            float,
    avg_win:             float,
    avg_loss:            float,
    entry_price:         float,
    stop_loss:           float,
    realized_vol_pct:    float = 2.0,
    # Plafonds de sécurité
    max_risk_per_trade:  float = 2.0,     # % max du capital à risquer (=risk réel sur SL)
    max_position_pct:    float = 20.0,    # % max du capital en une position
    kelly_fraction_used: float = 0.25,
    vol_target_pct:      float = 2.0,
    min_position_usdt:   float = 10.0,    # Binance min notional
) -> dict:
    """
    Calcule la taille de position OPTIMALE en combinant Kelly + Volatility + Cap.
    Retourne un dict complet avec le détail du raisonnement (pour audit).

    Philosophy :
        On prend le MINIMUM de 3 bornes :
          1. Kelly fractional (paramètre optimal si win_rate connu)
          2. Vol-adjusted size (ajustement à la volatilité courante)
          3. Max risk absolu (limite dure, protège contre gap)

    Retourne:
        {
            "size_usdt":      montant final à investir,
            "quantity":       quantité de coin (size_usdt / entry_price),
            "risk_usdt":      perte en USDT si SL touché,
            "risk_pct":       % du capital à risque,
            "kelly_f":        fraction Kelly utilisée,
            "vol_multiplier": multiplicateur de volatilité appliqué,
            "binding":        "kelly" | "vol" | "max_risk" | "max_position" | "min_notional"
        }
    """
    if entry_price <= 0 or stop_loss <= 0 or entry_price <= stop_loss:
        return {
            "size_usdt": 0, "quantity": 0, "risk_usdt": 0, "risk_pct": 0,
            "kelly_f": 0, "vol_multiplier": 1.0, "binding": "invalid_sl",
        }

    # Kelly-based sizing
    kelly_f = fractional_kelly(win_rate, avg_win, avg_loss, kelly_fraction_used)
    kelly_size = capital * kelly_f

    # Vol-adjusted sizing (base = max_risk / SL_distance_pct)
    sl_distance_pct = (entry_price - stop_loss) / entry_price * 100
    base_size_from_risk = (capital * max_risk_per_trade / 100) / (sl_distance_pct / 100)
    vol_multiplier = volatility_target_multiplier(realized_vol_pct, vol_target_pct)
    vol_adjusted_size = base_size_from_risk * vol_multiplier

    # Max position (% du capital)
    max_position_size = capital * max_position_pct / 100

    # Max risk absolu (à la perte)
    max_risk_size = (capital * max_risk_per_trade / 100) / (sl_distance_pct / 100)

    # Prendre le MIN des contraintes
    candidates = {
        "kelly":        kelly_size if kelly_f > 0 else max_position_size,
        "vol":          vol_adjusted_size,
        "max_risk":     max_risk_size,
        "max_position": max_position_size,
    }

    size_usdt = min(candidates.values())
    binding   = min(candidates, key=candidates.get)

    # Floor min notional Binance
    if size_usdt < min_position_usdt:
        return {
            "size_usdt": 0, "quantity": 0, "risk_usdt": 0, "risk_pct": 0,
            "kelly_f": kelly_f, "vol_multiplier": vol_multiplier,
            "binding": "min_notional",
        }

    quantity = size_usdt / entry_price
    risk_usdt = (entry_price - stop_loss) * quantity
    risk_pct  = risk_usdt / capital * 100 if capital > 0 else 0

    return {
        "size_usdt":      round(size_usdt, 2),
        "quantity":       round(quantity, 8),
        "risk_usdt":      round(risk_usdt, 2),
        "risk_pct":       round(risk_pct, 3),
        "kelly_f":        round(kelly_f, 4),
        "vol_multiplier": round(vol_multiplier, 3),
        "sl_distance_pct": round(sl_distance_pct, 3),
        "binding":        binding,
    }


# ─── Stats historiques pour alimenter Kelly ───────────────────────────────────

def compute_historical_stats(portfolio_type: str = "master",
                              min_trades: int = 10) -> dict:
    """
    Calcule win_rate / avg_win / avg_loss à partir des trades historiques.

    Matching entry/exit via la table open_positions (source de vérité des cycles
    de trade fermés). Les SELL sont joints avec une tolérance temporelle de 2
    secondes (écriture record_trade() suivi de close_open_position() sans gap).

    Retourne des valeurs par défaut conservatrices si moins de `min_trades`
    échantillons, avec le flag `is_defaults=True` qui doit DÉCLENCHER un
    mode cold-start côté appelant (ne pas utiliser Kelly au plein risque).
    """
    from core.database import get_connection

    try:
        with get_connection() as conn:
            # Join open_positions (closed) avec leur SELL correspondant
            # via proximité temporelle (< 2s entre record_trade et close_open_position).
            # NOTE : on capture AUTO_EXIT_% (TP/SL final) ET AUTO_PARTIAL_% (partial TP1)
            # car les deux représentent un événement de réalisation de profit/perte
            # qui doit alimenter les stats Kelly.
            rows = conn.execute(
                """SELECT op.entry_price    AS entry_price,
                          op.quantity       AS quantity,
                          op.entry_usdt     AS entry_usdt,
                          op.status         AS status,
                          (SELECT t.price FROM trades t
                           WHERE t.coin_id = op.coin_id
                             AND t.side = 'SELL'
                             AND (t.source LIKE ? OR t.source LIKE ?)
                             AND ABS(JULIANDAY(t.executed_at) - JULIANDAY(op.closed_at)) * 86400 < 2
                           ORDER BY t.executed_at DESC LIMIT 1) AS exit_price,
                          (SELECT t.fee FROM trades t
                           WHERE t.coin_id = op.coin_id
                             AND t.side = 'SELL'
                             AND (t.source LIKE ? OR t.source LIKE ?)
                             AND ABS(JULIANDAY(t.executed_at) - JULIANDAY(op.closed_at)) * 86400 < 2
                           ORDER BY t.executed_at DESC LIMIT 1) AS exit_fee
                   FROM open_positions op
                   WHERE op.portfolio_type = ?
                     AND op.status IN ('EXIT_TP', 'EXIT_SL', 'CLOSED_MANUAL')
                     AND op.closed_at IS NOT NULL
                   ORDER BY op.closed_at DESC
                   LIMIT 100""",
                (f"AUTO_EXIT_%_{portfolio_type.upper()}",
                 f"AUTO_PARTIAL_{portfolio_type.upper()}",
                 f"AUTO_EXIT_%_{portfolio_type.upper()}",
                 f"AUTO_PARTIAL_{portfolio_type.upper()}",
                 portfolio_type)
            ).fetchall()
    except (sqlite3.Error, ValueError, TypeError) as exc:
        import logging
        logging.getLogger("position_sizing").warning(f"compute_historical_stats: {exc}")
        rows = []

    pnls = []
    for r in rows:
        d = dict(r)
        entry = d.get("entry_price") or 0
        exit_ = d.get("exit_price")  or 0
        qty   = d.get("quantity")    or 0
        fee   = d.get("exit_fee")    or 0
        if exit_ > 0 and entry > 0 and qty > 0:
            # P&L net d'une position = (exit-entry)*qty - fees
            # Les fees d'entrée sont déjà dans entry_usdt (mais on ne les retranche
            # pas ici car on veut comparer gain vs risque initial, pas le P&L exact)
            pnl = (exit_ - entry) * qty - fee
            pnls.append(pnl)

    if len(pnls) < min_trades:
        # Pas assez de données — valeurs par défaut CONSERVATRICES
        # L'appelant doit utiliser is_defaults=True pour activer le mode cold-start
        return {
            "win_rate":      0.45,
            "avg_win":       20.0,
            "avg_loss":      10.0,
            "sample_size":   len(pnls),
            "is_defaults":   True,
        }

    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    if not wins or not losses:
        # Toutes gagnantes ou toutes perdantes = échantillon dégénéré
        return {
            "win_rate":      0.50,
            "avg_win":       abs(max(pnls)) if pnls else 10.0,
            "avg_loss":      abs(min(pnls)) if pnls else 10.0,
            "sample_size":   len(pnls),
            "is_defaults":   True,
        }

    return {
        "win_rate":    len(wins) / len(pnls),
        "avg_win":     sum(wins) / len(wins),
        "avg_loss":    abs(sum(losses) / len(losses)),
        "sample_size": len(pnls),
        "is_defaults": False,
    }


# ─── Volatility Estimation ────────────────────────────────────────────────────

def realized_volatility_pct(candles: list[dict], lookback: int = 30) -> float:
    """
    Calcule la volatilité réalisée en % à partir de N dernières bougies.
    Utilise l'ATR comme proxy de volatilité.
    """
    from core.indicators import atr

    if not candles or len(candles) < lookback + 1:
        return 2.0   # valeur par défaut

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]

    atr_values = atr(highs, lows, closes, period=14)
    if not atr_values:
        return 2.0
    last_atr = atr_values[-1]
    if last_atr is None or last_atr <= 0:
        return 2.0
    last_price = closes[-1]
    if last_price <= 0:
        return 2.0

    return (last_atr / last_price) * 100
