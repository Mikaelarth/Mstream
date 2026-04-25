"""
MstreamTrader - Métriques de Performance
==========================================

Calculs pure Python des métriques de qualité d'une stratégie de trading.
Utilisées par le moteur de backtesting et l'analyse post-mortem.

Toutes les fonctions sont SANS dépendance externe (compat Android).

Réf. :
    - Sharpe ratio:  Sharpe (1966) — (return − rf) / volatility, annualisé
    - Sortino ratio: Sortino (1994) — ne pénalise que la volatilité négative
    - Calmar ratio:  return annualisé / max drawdown
    - Profit factor: Σ(gains) / Σ(pertes) — > 1.0 est rentable, > 1.5 est bon
    - Expectancy:    valeur espérée d'un trade moyen
    - R-multiple:    P&L / risque initial — mesure la qualité du trade
"""

import math


# ─── Retours & Courbe d'équité ────────────────────────────────────────────────

def total_return_pct(initial: float, final: float) -> float:
    """Rendement total en %."""
    if initial <= 0:
        return 0.0
    return (final - initial) / initial * 100


def annualized_return_pct(initial: float, final: float, days: float) -> float:
    """Rendement annualisé (CAGR) — formule: (1 + r)^(365/days) − 1."""
    if initial <= 0 or days <= 0:
        return 0.0
    total = final / initial
    if total <= 0:
        return -100.0
    return (total ** (365.0 / days) - 1) * 100


def period_returns(equity_curve: list[float]) -> list[float]:
    """Retours pas-à-pas d'une courbe d'équité (returns simples)."""
    if len(equity_curve) < 2:
        return []
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        curr = equity_curve[i]
        if prev > 0:
            returns.append((curr - prev) / prev)
    return returns


# ─── Drawdown ─────────────────────────────────────────────────────────────────

def max_drawdown_pct(equity_curve: list[float]) -> float:
    """
    Max drawdown en % : pire chute depuis un sommet (peak-to-trough).
    Retourne une valeur positive (5.3 = perte de 5.3 %).
    """
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return max_dd


def drawdown_duration_candles(equity_curve: list[float]) -> int:
    """Nombre de bougies dans le pire drawdown (temps passé sous le peak)."""
    if not equity_curve:
        return 0
    peak = equity_curve[0]
    peak_idx = 0
    max_duration = 0
    for i, value in enumerate(equity_curve):
        if value >= peak:
            peak = value
            peak_idx = i
        else:
            duration = i - peak_idx
            if duration > max_duration:
                max_duration = duration
    return max_duration


# ─── Ratios risk-adjusted ─────────────────────────────────────────────────────

def sharpe_ratio(returns: list[float], periods_per_year: int = 252,
                 risk_free_rate: float = 0.0) -> float:
    """
    Sharpe ratio annualisé.
    > 1 est bon, > 2 est excellent, > 3 est exceptionnel.

    periods_per_year : 252 pour daily, 6*365=2190 pour 4h candles, 24*365=8760 pour 1h
    """
    if not returns or len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    excess = mean - risk_free_rate / periods_per_year
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std <= 0:
        return 0.0
    return (excess / std) * math.sqrt(periods_per_year)


def sortino_ratio(returns: list[float], periods_per_year: int = 252,
                  risk_free_rate: float = 0.0) -> float:
    """
    Sortino ratio — comme Sharpe mais ne pénalise que la downside.
    > 1 est bon, > 2 est excellent.
    """
    if not returns or len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    excess = mean - risk_free_rate / periods_per_year
    downside = [r for r in returns if r < 0]
    if not downside:
        return float("inf") if excess > 0 else 0.0
    downside_variance = sum(r ** 2 for r in downside) / len(returns)
    downside_std = math.sqrt(downside_variance)
    if downside_std <= 0:
        return 0.0
    return (excess / downside_std) * math.sqrt(periods_per_year)


def calmar_ratio(annualized_return: float, max_drawdown: float) -> float:
    """
    Calmar ratio : rendement annualisé / max drawdown.
    > 1 est acceptable, > 3 est excellent.
    """
    if max_drawdown <= 0:
        return float("inf") if annualized_return > 0 else 0.0
    return annualized_return / max_drawdown


# ─── Analyse des trades ───────────────────────────────────────────────────────

def win_rate_pct(trades: list[dict]) -> float:
    """Pourcentage de trades gagnants (pnl > 0)."""
    closed = [t for t in trades if "pnl" in t]
    if not closed:
        return 0.0
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return wins / len(closed) * 100


def profit_factor(trades: list[dict]) -> float:
    """
    Profit Factor = Σ(gains) / |Σ(pertes)|.
    > 1.0 = stratégie rentable, > 1.5 = bon, > 2.0 = excellent.
    """
    gains  = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
    losses = sum(-t["pnl"] for t in trades if t.get("pnl", 0) < 0)
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def expectancy(trades: list[dict]) -> float:
    """Valeur espérée d'un trade moyen en USDT."""
    if not trades:
        return 0.0
    return sum(t.get("pnl", 0) for t in trades) / len(trades)


def avg_win_loss(trades: list[dict]) -> tuple[float, float]:
    """Retourne (gain moyen, perte moyenne). Perte retournée en positif."""
    wins   = [t["pnl"] for t in trades if t.get("pnl", 0) > 0]
    losses = [-t["pnl"] for t in trades if t.get("pnl", 0) < 0]
    avg_w  = sum(wins) / len(wins) if wins else 0.0
    avg_l  = sum(losses) / len(losses) if losses else 0.0
    return avg_w, avg_l


def r_multiple_stats(trades: list[dict]) -> dict:
    """
    Stats sur les R-multiples (P&L / risque initial).
    R-moyen > 0.3 est correct, > 0.5 est bon, > 1.0 est excellent.
    """
    rs = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    if not rs:
        return {"avg": 0.0, "median": 0.0, "best": 0.0, "worst": 0.0, "count": 0}
    srs = sorted(rs)
    n   = len(srs)
    median = srs[n // 2] if n % 2 == 1 else (srs[n // 2 - 1] + srs[n // 2]) / 2
    return {
        "avg":    sum(rs) / n,
        "median": median,
        "best":   max(rs),
        "worst":  min(rs),
        "count":  n,
    }


# ─── Rapport consolidé ────────────────────────────────────────────────────────

def compute_full_report(
    trades: list[dict],
    equity_curve: list[float],
    initial_capital: float,
    final_capital: float,
    duration_days: float,
    periods_per_year: int = 2190,   # 4h candles par défaut (6/jour × 365)
) -> dict:
    """
    Rapport complet prêt à afficher. Consomme :
        - trades : liste de dicts {pnl, r_multiple, ...}
        - equity_curve : valeur totale du portefeuille à chaque bougie
        - initial_capital, final_capital
        - duration_days : durée du backtest
    """
    returns = period_returns(equity_curve)
    total_r = total_return_pct(initial_capital, final_capital)
    ann_r   = annualized_return_pct(initial_capital, final_capital, duration_days)
    max_dd  = max_drawdown_pct(equity_curve)
    dd_dur  = drawdown_duration_candles(equity_curve)
    sharpe  = sharpe_ratio(returns, periods_per_year)
    sortino = sortino_ratio(returns, periods_per_year)
    calmar  = calmar_ratio(ann_r, max_dd)

    winners = [t for t in trades if t.get("pnl", 0) > 0]
    losers  = [t for t in trades if t.get("pnl", 0) < 0]
    avg_w, avg_l = avg_win_loss(trades)
    r_stats = r_multiple_stats(trades)

    return {
        # Capital
        "initial_capital":   round(initial_capital, 2),
        "final_capital":     round(final_capital, 2),
        "total_return_pct":  round(total_r, 2),
        "annualized_return": round(ann_r, 2),

        # Risque
        "max_drawdown_pct":  round(max_dd, 2),
        "max_dd_duration":   dd_dur,

        # Ratios risk-adjusted
        "sharpe":            round(sharpe, 3),
        "sortino":           round(sortino, 3),
        "calmar":            round(calmar, 3),

        # Trades
        "total_trades":      len(trades),
        "winners":           len(winners),
        "losers":            len(losers),
        "win_rate_pct":      round(win_rate_pct(trades), 2),
        "profit_factor":     round(profit_factor(trades), 3),
        "expectancy_usdt":   round(expectancy(trades), 2),
        "avg_win_usdt":      round(avg_w, 2),
        "avg_loss_usdt":     round(avg_l, 2),
        "best_trade_usdt":   round(max((t.get("pnl", 0) for t in trades), default=0), 2),
        "worst_trade_usdt":  round(min((t.get("pnl", 0) for t in trades), default=0), 2),

        # R-multiples
        "r_avg":             round(r_stats["avg"], 3),
        "r_median":          round(r_stats["median"], 3),
        "r_best":            round(r_stats["best"], 3),
        "r_worst":           round(r_stats["worst"], 3),
    }


def format_report(report: dict) -> str:
    """Formate un rapport en texte lisible pour console/log."""
    ok = "✓"

    def tag(cond, pos="[BON]", neg="[FAIBLE]"):
        return pos if cond else neg

    lines = [
        "═════════════════════════════════════════════════════════════",
        "              RAPPORT DE BACKTEST — Bot Maître              ",
        "═════════════════════════════════════════════════════════════",
        "",
        f"  CAPITAL",
        f"    Initial         :   ${report['initial_capital']:>12,.2f}",
        f"    Final           :   ${report['final_capital']:>12,.2f}",
        f"    Rendement total :   {report['total_return_pct']:>+10.2f} %",
        f"    Rendement annu. :   {report['annualized_return']:>+10.2f} %",
        "",
        f"  RISQUE",
        f"    Max Drawdown    :   {report['max_drawdown_pct']:>10.2f} %   "
        f"{tag(report['max_drawdown_pct'] < 15, '[ACCEPTABLE]', '[ÉLEVÉ]')}",
        f"    Durée max DD    :   {report['max_dd_duration']:>10} bougies",
        "",
        f"  RATIOS RISK-ADJUSTED",
        f"    Sharpe Ratio    :   {report['sharpe']:>10.3f}   "
        f"{tag(report['sharpe'] > 1.0, '[BON]', '[FAIBLE]')}",
        f"    Sortino Ratio   :   {report['sortino']:>10.3f}   "
        f"{tag(report['sortino'] > 1.5, '[BON]', '[FAIBLE]')}",
        f"    Calmar Ratio    :   {report['calmar']:>10.3f}   "
        f"{tag(report['calmar'] > 1.0, '[BON]', '[FAIBLE]')}",
        "",
        f"  TRADES",
        f"    Total           :   {report['total_trades']:>10}",
        f"    Gagnants        :   {report['winners']:>10}  ({report['win_rate_pct']:.1f} %)",
        f"    Perdants        :   {report['losers']:>10}",
        f"    Profit Factor   :   {report['profit_factor']:>10.3f}   "
        f"{tag(report['profit_factor'] > 1.5, '[RENTABLE]', '[MARGINAL]')}",
        f"    Expectancy      :   ${report['expectancy_usdt']:>+9.2f}  / trade",
        "",
        f"  STATISTIQUES TRADES",
        f"    Gain moyen      :   ${report['avg_win_usdt']:>+9.2f}",
        f"    Perte moyenne   :   ${report['avg_loss_usdt']:>+9.2f}",
        f"    Meilleur trade  :   ${report['best_trade_usdt']:>+9.2f}",
        f"    Pire trade      :   ${report['worst_trade_usdt']:>+9.2f}",
        "",
        f"  R-MULTIPLES (P&L / risque initial)",
        f"    R moyen         :   {report['r_avg']:>+10.3f}   "
        f"{tag(report['r_avg'] > 0.3, '[POSITIF]', '[NÉGATIF]')}",
        f"    R médian        :   {report['r_median']:>+10.3f}",
        f"    R meilleur      :   {report['r_best']:>+10.3f}",
        f"    R pire          :   {report['r_worst']:>+10.3f}",
        "═════════════════════════════════════════════════════════════",
    ]
    return "\n".join(lines)
