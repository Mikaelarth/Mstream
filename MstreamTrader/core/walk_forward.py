"""
MstreamTrader - Walk-Forward Analysis
=======================================

Méthode de validation hors-sample utilisée dans les hedge funds et publications
académiques. Un backtest simple peut être **overfit** (paramètres optimisés
spécifiquement pour cette période passée) et ne pas survivre en réel.

Walk-Forward :
    1. Découpe l'historique en N fenêtres glissantes de taille W
    2. Pour chaque fenêtre : train sur les premiers X %, test sur les Y % restants
    3. Agrège les résultats des périodes OUT-OF-SAMPLE uniquement
    4. Si les OOS sont cohérents → la stratégie est robuste

Différent du backtest standard :
    - Standard : 1 test sur 90 jours → "ça a marché"
    - Walk-forward : 5 tests OOS sur fenêtres de 30 jours décalées → "ça marche de façon robuste"

Exemple avec 120 jours, window=60, step=30 :
    Fenêtre 1 : j0-j60    (train 0-42, test 42-60)
    Fenêtre 2 : j30-j90   (train 30-72, test 72-90)
    Fenêtre 3 : j60-j120  (train 60-102, test 102-120)

On ne backteste que les parties test (out-of-sample).
Le résultat final moyenne les métriques sur toutes les périodes OOS.
"""

from dataclasses import dataclass, field
from typing import Optional

from core.backtest import Backtest, BacktestConfig, BacktestResult
from core.metrics import compute_full_report


@dataclass
class WalkForwardWindow:
    """Une fenêtre de walk-forward."""
    window_idx:    int
    start_ts:      float
    end_ts:        float
    test_start_ts: float
    result:        BacktestResult


@dataclass
class WalkForwardResult:
    """Résultat agrégé d'un walk-forward."""
    windows:             list   = field(default_factory=list)
    n_windows:           int   = 0
    aggregated_metrics:  dict  = field(default_factory=dict)
    consistency_score:   float = 0.0   # 0 à 1 : cohérence des résultats OOS
    is_robust:           bool  = False


def run_walk_forward(
    coins_data: dict,
    config: BacktestConfig,
    window_days: int = 60,
    step_days:   int = 30,
    train_ratio: float = 0.7,
    btc_daily_history: Optional[list] = None,
    verbose: bool = True,
) -> WalkForwardResult:
    """
    Lance un walk-forward analysis.

    Args:
        coins_data        : données par coin (doit couvrir au moins 2 × window_days)
        config            : BacktestConfig de base
        window_days       : taille d'une fenêtre complète
        step_days         : décalage entre fenêtres
        train_ratio       : fraction train/test (on teste seulement la fraction OOS)
        btc_daily_history : pour le filtre régime si actif
        verbose           : affichage console

    Retourne un WalkForwardResult avec toutes les fenêtres + agrégation.
    """
    if not coins_data:
        return WalkForwardResult()

    # Timestamps communs
    all_ts = sorted(set.intersection(*[
        {c["timestamp"] for c in candles} for candles in coins_data.values()
    ]))
    if len(all_ts) < 100:
        raise ValueError("Pas assez de bougies pour walk-forward")

    duration_sec  = all_ts[-1] - all_ts[0]
    duration_days = duration_sec / 86400

    if duration_days < window_days * 1.5:
        raise ValueError(
            f"Historique insuffisant ({duration_days:.1f}j) pour windows de {window_days}j"
        )

    # Calculer les fenêtres
    windows: list[tuple[float, float, float]] = []   # (start, test_start, end)
    cursor_day = 0
    while cursor_day + window_days <= duration_days:
        start_ts  = all_ts[0] + cursor_day * 86400
        end_ts    = start_ts + window_days * 86400
        train_end = start_ts + window_days * train_ratio * 86400
        windows.append((start_ts, train_end, end_ts))
        cursor_day += step_days

    if verbose:
        print(f"Walk-forward : {len(windows)} fenetres x {window_days}j (step {step_days}j)")
        print(f"Historique couvert : {duration_days:.1f} jours")
        print(f"Train ratio        : {train_ratio*100:.0f}% / Test {(1-train_ratio)*100:.0f}%")
        print()

    wf_windows = []

    for i, (start_ts, test_start_ts, end_ts) in enumerate(windows):
        # Extraire les bougies de cette fenêtre (partie OOS uniquement)
        window_data = {}
        for cid, candles in coins_data.items():
            # On garde TOUTES les bougies jusqu'à end_ts (pour calculer les indicateurs)
            # mais on ne trade QUE dans la fenêtre [test_start_ts, end_ts]
            # Ceci est approximé via le warmup : les bougies avant test_start_ts
            # servent de warmup
            subset = [c for c in candles if c["timestamp"] <= end_ts]
            window_data[cid] = subset

        # Calculer le warmup correct pour faire commencer le trading à test_start_ts
        # On prend la différence en bougies entre start_ts et test_start_ts
        first_cid = next(iter(window_data))
        first_candles = window_data[first_cid]
        warmup_idx = 0
        for j, c in enumerate(first_candles):
            if c["timestamp"] >= test_start_ts:
                warmup_idx = j
                break
        # Clone de la config avec warmup ajusté
        cfg_copy = BacktestConfig(**{**config.__dict__, "warmup_candles": max(60, warmup_idx)})

        bt = Backtest(cfg_copy)
        try:
            result = bt.run(window_data, btc_daily_history=btc_daily_history)
        except Exception as exc:
            if verbose:
                print(f"  Fenetre {i+1}/{len(windows)} : ECHEC ({exc})")
            continue

        wf_windows.append(WalkForwardWindow(
            window_idx    = i,
            start_ts      = start_ts,
            end_ts        = end_ts,
            test_start_ts = test_start_ts,
            result        = result,
        ))

        if verbose:
            r = result.report
            print(f"  Fenetre {i+1:>2}/{len(windows)} : "
                  f"return={r['total_return_pct']:>+6.2f}%  "
                  f"Sh={r['sharpe']:>5.2f}  "
                  f"PF={r['profit_factor']:>5.2f}  "
                  f"DD={r['max_drawdown_pct']:>5.2f}%  "
                  f"trades={r['total_trades']:>3}")

    # Agrégation
    if not wf_windows:
        return WalkForwardResult(windows=[], n_windows=0)

    returns = [w.result.report["total_return_pct"] for w in wf_windows]
    sharpes = [w.result.report["sharpe"]           for w in wf_windows]
    pfs     = [w.result.report["profit_factor"]    for w in wf_windows
               if w.result.report["profit_factor"] < 999]
    dds     = [w.result.report["max_drawdown_pct"] for w in wf_windows]
    trades_total = sum(w.result.report["total_trades"] for w in wf_windows)

    avg_return = sum(returns) / len(returns)
    avg_sharpe = sum(sharpes) / len(sharpes)
    avg_pf     = sum(pfs) / len(pfs) if pfs else 0
    avg_dd     = sum(dds) / len(dds)

    # Consistency : % de fenêtres avec return > 0
    positive_windows = sum(1 for r in returns if r > 0)
    consistency = positive_windows / len(returns)

    # Robustesse : consistency > 0.6 ET avg_sharpe > 0.5 ET avg_pf > 1.2
    is_robust = (consistency > 0.6 and avg_sharpe > 0.5 and avg_pf > 1.2)

    aggregated = {
        "avg_return_pct":    round(avg_return, 2),
        "std_return":        round((sum((r - avg_return)**2 for r in returns) / len(returns)) ** 0.5, 2),
        "avg_sharpe":        round(avg_sharpe, 3),
        "avg_profit_factor": round(avg_pf, 3),
        "avg_max_dd":        round(avg_dd, 2),
        "total_trades":      trades_total,
        "windows_positive":  positive_windows,
        "windows_negative":  len(returns) - positive_windows,
        "consistency_pct":   round(consistency * 100, 2),
    }

    if verbose:
        print()
        print("AGREGATION:")
        for k, v in aggregated.items():
            print(f"  {k:<20}: {v}")
        print()
        print(f"  Strategie ROBUSTE : {'OUI' if is_robust else 'NON'}")

    return WalkForwardResult(
        windows=wf_windows,
        n_windows=len(wf_windows),
        aggregated_metrics=aggregated,
        consistency_score=consistency,
        is_robust=is_robust,
    )
