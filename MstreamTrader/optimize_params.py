"""
MstreamTrader - Optimiseur de Paramètres (Grid Search)
========================================================

Teste systématiquement toutes les combinaisons d'un jeu de paramètres
sur les mêmes données historiques et classe les résultats selon un score
composite multi-critères (Sharpe × Profit Factor − pénalité Drawdown).

Usage :
    python optimize_params.py                           # grille par défaut
    python optimize_params.py --days 60 --top 20
    python optimize_params.py --coins bitcoin,ethereum --regime
    python optimize_params.py --save best_params.json

Notes :
    - Le grid search est lourd : 5 × 4 × 4 = 80 combinaisons par défaut
    - Durée ~ 2-5 min sur un CPU standard (pour 60 jours × 4 coins × 1h candles)
    - Les données sont téléchargées UNE SEULE FOIS puis réutilisées par toutes les runs
    - Une configuration est "déployable" si : trades ≥ 15, Sharpe > 0.8, PF > 1.3, DD < 25 %

Ranking composite :
    quality_score = (Sharpe × Profit_Factor × √trade_count/30)
                   − (max_drawdown_pct × 0.05)
    + bonus si rendement annualisé > 30 %
"""

import argparse
import json
import math
import sys
import itertools
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from core import market_data
from core.backtest import Backtest, BacktestConfig


# ─── Grilles de paramètres par défaut ────────────────────────────────────────

DEFAULT_GRID = {
    "min_score":     [45, 50, 55, 60, 65],
    "min_rr":        [2.0, 2.5, 3.0, 3.5],
    "risk_pct":      [2.0, 3.5, 5.0, 7.5],
    "max_positions": [3, 4, 5],
}


# ─── Score composite ──────────────────────────────────────────────────────────

def compute_quality_score(report: dict) -> float:
    """
    Score composite pour classer les configurations.

    Philosophie :
        - Sharpe × PF capture la rentabilité risk-adjusted
        - Racine carrée du nombre de trades pénalise les échantillons trop petits
        - Max DD × 0.05 pénalise le risque réalisé
        - Bonus si rendement annualisé > 30 %
        - Malus sévère si win rate < 30 % ou trades < 10
    """
    trades        = report["total_trades"]
    sharpe        = report["sharpe"]
    pf            = report["profit_factor"]
    max_dd        = report["max_drawdown_pct"]
    ann_return    = report["annualized_return"]
    win_rate      = report["win_rate_pct"]

    # Disqualifications
    if trades < 5:
        return -999.0
    if win_rate < 25:
        return -500.0
    if pf == 0 or not math.isfinite(pf):
        return -500.0

    # PF plafonné à 5 pour éviter l'explosion des petits échantillons
    pf_capped = min(pf, 5.0)
    sharpe_capped = max(min(sharpe, 5.0), -2.0)

    # Score base : risk-adjusted × sample quality
    sample_factor = min(math.sqrt(trades / 30), 1.5)
    base = sharpe_capped * pf_capped * sample_factor

    # Pénalité drawdown
    dd_penalty = max_dd * 0.05

    # Bonus rendement annualisé
    ret_bonus = 0.0
    if ann_return > 30:
        ret_bonus = min((ann_return - 30) / 100, 1.0)

    return round(base - dd_penalty + ret_bonus, 3)


def is_deployable(report: dict) -> bool:
    """Retourne True si la configuration passe les critères de déploiement."""
    return (
        report["total_trades"]      >= 15 and
        report["sharpe"]            > 0.8  and
        report["profit_factor"]     > 1.3  and
        report["max_drawdown_pct"]  < 25.0 and
        report["win_rate_pct"]      > 35.0
    )


# ─── Grid search ──────────────────────────────────────────────────────────────

def run_grid_search(coins_data: dict, grid: dict, base_cfg: BacktestConfig,
                    use_regime: bool = False, verbose: bool = True,
                    walk_forward: bool = False,
                    wf_window_days: int = 30, wf_step_days: int = 10,
                    btc_daily: Optional[list] = None) -> list[dict]:
    """
    Lance un backtest (classique ou walk-forward) pour chaque combinaison du grid.
    Retourne une liste triée par quality_score desc.

    Si walk_forward=True, chaque configuration est validée sur plusieurs fenêtres
    hors-sample glissantes. Les résultats utilisent les métriques moyennes OOS.
    """
    from core.walk_forward import run_walk_forward

    param_names = list(grid.keys())
    combinations = list(itertools.product(*[grid[k] for k in param_names]))

    total = len(combinations)
    if verbose:
        mode = "WALK-FORWARD" if walk_forward else "STANDARD"
        print(f"Grid search ({mode}) : {total} combinaisons à tester...")
        print(f"  {' × '.join(f'{len(grid[k])} {k}' for k in param_names)}")
        if walk_forward:
            print(f"  Fenêtres walk-forward : {wf_window_days}j (step {wf_step_days}j)")
        print()

    results = []
    for i, combo in enumerate(combinations, 1):
        params = dict(zip(param_names, combo))

        cfg_dict = {**base_cfg.__dict__, **params, "use_regime_filter": use_regime}
        cfg = BacktestConfig(**cfg_dict)

        try:
            if walk_forward:
                wf_result = run_walk_forward(
                    coins_data, cfg,
                    window_days=wf_window_days, step_days=wf_step_days,
                    btc_daily_history=btc_daily, verbose=False,
                )
                if wf_result.n_windows == 0:
                    if verbose:
                        print(f"  {i:>3}/{total} SKIP {params} (pas assez de fenetres)")
                    continue
                # Agrégation RÉELLE des trades de toutes les fenêtres OOS
                # (anciennement : win_rate hardcodé à 50 → is_deployable biaisé)
                all_wf_trades = []
                for w in wf_result.windows:
                    all_wf_trades.extend(w.result.trades)

                wins   = [t["pnl"] for t in all_wf_trades if t.get("pnl", 0) > 0]
                losses = [-t["pnl"] for t in all_wf_trades if t.get("pnl", 0) < 0]
                rs     = [t.get("r_multiple", 0) for t in all_wf_trades
                          if t.get("r_multiple") is not None]

                total_tr = len(all_wf_trades)
                win_rate = (len(wins) / total_tr * 100) if total_tr else 0.0
                avg_win  = (sum(wins)   / len(wins))   if wins   else 0.0
                avg_loss = (sum(losses) / len(losses)) if losses else 0.0
                expectancy = (sum(t.get("pnl", 0) for t in all_wf_trades) / total_tr
                              if total_tr else 0.0)

                agg = wf_result.aggregated_metrics
                report = {
                    "total_return_pct":  agg["avg_return_pct"],
                    "annualized_return": agg["avg_return_pct"] * (365 / wf_window_days),
                    "max_drawdown_pct":  agg["avg_max_dd"],
                    "sharpe":            agg["avg_sharpe"],
                    "sortino":           agg["avg_sharpe"] * 1.3,
                    "calmar":            (agg["avg_return_pct"] / agg["avg_max_dd"]) if agg["avg_max_dd"] > 0 else 0,
                    "total_trades":      total_tr,
                    "winners":           len(wins),
                    "losers":            len(losses),
                    "win_rate_pct":      round(win_rate, 2),
                    "profit_factor":     agg["avg_profit_factor"],
                    "expectancy_usdt":   round(expectancy, 2),
                    "avg_win_usdt":      round(avg_win, 2),
                    "avg_loss_usdt":     round(avg_loss, 2),
                    "best_trade_usdt":   round(max((t.get("pnl", 0) for t in all_wf_trades), default=0), 2),
                    "worst_trade_usdt":  round(min((t.get("pnl", 0) for t in all_wf_trades), default=0), 2),
                    "r_avg":             round(sum(rs) / len(rs), 3) if rs else 0,
                    "r_median":          round(sorted(rs)[len(rs)//2], 3) if rs else 0,
                    "r_best":            round(max(rs), 3) if rs else 0,
                    "r_worst":           round(min(rs), 3) if rs else 0,
                    "consistency_pct":   agg["consistency_pct"],
                    "is_robust":         wf_result.is_robust,
                    "n_windows":         wf_result.n_windows,
                    "std_return":        agg["std_return"],
                }
                quality = compute_quality_score(report)
                # Bonus robustesse walk-forward
                if wf_result.is_robust:
                    quality += 1.0
                deployable = is_deployable(report) and wf_result.is_robust
                result_payload = {
                    "params":       params,
                    "quality":      quality,
                    "deployable":   deployable,
                    "report":       report,
                    "wf_windows":   wf_result.n_windows,
                    "wf_robust":    wf_result.is_robust,
                    "wf_consistency": agg["consistency_pct"],
                }
                if verbose:
                    flag = "[V]" if deployable else "[x]"
                    rob = "ROB" if wf_result.is_robust else "   "
                    print(f"  {i:>3}/{total} {flag} {rob} "
                          f"score={quality:>+6.2f} "
                          f"ret_avg={agg['avg_return_pct']:>+6.2f}% "
                          f"Sh={agg['avg_sharpe']:>5.2f} "
                          f"PF={agg['avg_profit_factor']:>5.2f} "
                          f"DD_avg={agg['avg_max_dd']:>5.2f}% "
                          f"cons={agg['consistency_pct']:>5.1f}% "
                          f"trades={agg['total_trades']:>4} "
                          f"wins={wf_result.n_windows}")
                results.append(result_payload)
            else:
                bt = Backtest(cfg)
                result = bt.run(coins_data, btc_daily_history=btc_daily)
                quality = compute_quality_score(result.report)
                deployable = is_deployable(result.report)

                results.append({
                    "params":       params,
                    "quality":      quality,
                    "deployable":   deployable,
                    "report":       result.report,
                    "regime_distribution": result.regime_distribution,
                    "trades_by_regime":    result.trades_by_regime,
                })

                if verbose:
                    flag = "[V]" if deployable else "[x]"
                    print(f"  {i:>3}/{total} {flag}  "
                          f"score={quality:>+6.2f}  "
                          f"ret={result.report['total_return_pct']:>+6.2f}%  "
                          f"Sh={result.report['sharpe']:>5.2f}  "
                          f"PF={result.report['profit_factor']:>5.2f}  "
                          f"DD={result.report['max_drawdown_pct']:>5.2f}%  "
                          f"trades={result.report['total_trades']:>3}  "
                          f"| {params}")
        except Exception as exc:
            if verbose:
                print(f"  {i:>3}/{total} ERR  {params} : {exc}")
            continue

    results.sort(key=lambda r: r["quality"], reverse=True)
    return results


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Grid search d'optimisation des paramètres du Bot Maître",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--days",     type=int,   default=60,
                   help="Jours d'historique (défaut: 60)")
    p.add_argument("--interval", type=str,   default="1h",
                   choices=["15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"],
                   help="Granularité bougies (défaut: 1h)")
    p.add_argument("--coins",    type=str,   default="bitcoin,ethereum,solana,binancecoin",
                   help="Coin IDs séparés par virgule")
    p.add_argument("--capital",  type=float, default=1000.0)
    p.add_argument("--regime",   action="store_true",
                   help="Activer le filtre de régime bull/bear")
    p.add_argument("--top",      type=int,   default=10,
                   help="Nombre de meilleures configs à afficher (défaut: 10)")
    p.add_argument("--save",     type=str,
                   help="Sauver tous les résultats triés en JSON")
    # Walk-forward
    p.add_argument("--walk-forward", action="store_true",
                   help="Utiliser walk-forward analysis (valide sur fenêtres hors-sample)")
    p.add_argument("--wf-window",    type=int, default=30,
                   help="Taille d'une fenêtre walk-forward en jours (défaut: 30)")
    p.add_argument("--wf-step",      type=int, default=10,
                   help="Décalage entre fenêtres walk-forward (défaut: 10)")
    return p.parse_args()


def print_top(results: list[dict], n: int):
    print()
    print("=" * 120)
    print(f" TOP {min(n, len(results))} CONFIGURATIONS PAR QUALITY SCORE")
    print("=" * 120)
    hdr = (f"{'#':>3}  {'Score':>7}  {'Deploy':>6}  "
           f"{'Score filtre':>13}  {'R/R min':>8}  {'Risk':>5}  {'MaxPos':>6}  "
           f"{'Return':>8}  {'Sharpe':>6}  {'PF':>5}  {'DD':>6}  {'WinR':>6}  {'Trd':>4}")
    print(hdr)
    print("-" * 120)
    for i, res in enumerate(results[:n], 1):
        p = res["params"]
        r = res["report"]
        dep = "V" if res["deployable"] else "-"
        print(f"{i:>3}  {res['quality']:>+7.2f}  {dep:>6}  "
              f"{p.get('min_score', '-'):>13}  "
              f"{p.get('min_rr', '-'):>8}  "
              f"{p.get('risk_pct', '-'):>4}%  "
              f"{p.get('max_positions', '-'):>6}  "
              f"{r['total_return_pct']:>+7.2f}%  "
              f"{r['sharpe']:>6.2f}  "
              f"{r['profit_factor']:>5.2f}  "
              f"{r['max_drawdown_pct']:>5.2f}%  "
              f"{r['win_rate_pct']:>5.1f}%  "
              f"{r['total_trades']:>4}")
    print("=" * 120)


def main():
    args = parse_args()
    coin_ids = [c.strip() for c in args.coins.split(",") if c.strip()]

    # 1. Télécharger les données (une seule fois)
    print(f"Téléchargement {args.days} jours x {args.interval} x {len(coin_ids)} coins...")
    coins_data = {}
    for cid in coin_ids:
        c = market_data.get_ohlcv_for_analysis(cid, days=args.days, interval=args.interval)
        if c and len(c) >= 100:
            coins_data[cid] = c
            print(f"  - {cid:20} : {len(c)} bougies")
        else:
            print(f"  - {cid:20} : ECHEC ({len(c) if c else 0} bougies)")
    if not coins_data:
        print("ERREUR : aucune donnée récupérée.")
        sys.exit(1)
    print()

    # 2. Config de base (selon la granularité)
    secs_per_candle = {"15m":900, "30m":1800, "1h":3600, "2h":7200,
                       "4h":14400, "6h":21600, "12h":43200, "1d":86400}.get(args.interval, 3600)
    periods_year = int(86400 * 365 / secs_per_candle)

    base_cfg = BacktestConfig(
        initial_capital     = args.capital,
        periods_per_year    = periods_year,
        candle_duration_sec = secs_per_candle,
        cooldown_candles    = max(1, 21600 // secs_per_candle),
        use_regime_filter   = args.regime,
        # Filtres avancés OFF par défaut en grid search :
        # ils rejettent quasi tout sur des historiques courts/calmes (constaté
        # empiriquement : 0 trades sur 240 configs avec ensemble + mtf
        # + correlation activés). Le grid search valide la stratégie de BASE.
        # Le bot LIVE garde ces filtres ON pour la rigueur en production.
        use_ensemble        = False,
        use_mtf_confluence  = False,
        use_correlation_block = False,
    )

    # 3. Fetch BTC daily si régime activé (pour le filtre bull/bear)
    btc_daily = None
    if args.regime:
        try:
            btc_daily = market_data.get_binance_klines_public(
                "bitcoin", interval="1d", limit=500
            )
            if btc_daily and len(btc_daily) >= 200:
                print(f"  BTC daily récupéré : {len(btc_daily)} bougies (pour régime)")
            else:
                print(f"  ATTENTION : BTC daily insuffisant, régime desactive")
                btc_daily = None
        except Exception as exc:
            print(f"  Echec fetch BTC daily : {exc}")
            btc_daily = None
        print()

    # 4. Lancer le grid search
    results = run_grid_search(
        coins_data, DEFAULT_GRID, base_cfg,
        use_regime=args.regime,
        walk_forward=args.walk_forward,
        wf_window_days=args.wf_window,
        wf_step_days=args.wf_step,
        btc_daily=btc_daily,
        verbose=True,
    )

    # 4. Afficher le top
    print_top(results, args.top)

    # 5. Résumé
    deployable_count = sum(1 for r in results if r["deployable"])
    print()
    print(f"  {deployable_count}/{len(results)} configurations déployables "
          f"(trades >= 15, Sharpe > 0.8, PF > 1.3, DD < 25%)")

    if results and results[0]["quality"] > 0:
        best = results[0]
        print()
        print("  MEILLEURE CONFIGURATION")
        print(f"    {best['params']}")
        print(f"    Quality score : {best['quality']:+.2f}")
        print(f"    Deployable    : {'OUI' if best['deployable'] else 'NON'}")
        if best["deployable"]:
            print()
            print("  Pour appliquer ces paramètres au Bot Maître :")
            print(f"    Dans l'app, aller dans Configuration > Bot Maître")
            print(f"    Ajuster le risque par trade à {best['params']['risk_pct']}%")
            print("    Les autres paramètres sont hardcodés dans core/auto_trader.py:MASTER_CONFIG")

    # 6. Sauvegarde JSON
    if args.save:
        payload = {
            "grid":    DEFAULT_GRID,
            "days":    args.days,
            "coins":   list(coins_data.keys()),
            "regime":  args.regime,
            "results": results,
        }
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  Résultats complets sauvegardés : {args.save}")


if __name__ == "__main__":
    main()
