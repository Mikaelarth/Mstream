"""
MstreamTrader - CLI Backtesting Runner
========================================

Usage :
    python run_backtest.py                      # tous les coins, 90 jours, $1000
    python run_backtest.py --days 30            # 30 jours
    python run_backtest.py --capital 5000       # $5000 initial
    python run_backtest.py --coins bitcoin,ethereum
    python run_backtest.py --verbose            # détail des trades
    python run_backtest.py --risk 3 --max-positions 3
    python run_backtest.py --save result.json   # sauver le résultat en JSON

Le backtest utilise les données CoinGecko (gratuit, sans clé API).
Granularité des bougies selon la durée :
    ≤ 1 jour    → 30 minutes
    ≤ 90 jours  → 4 heures
    > 90 jours  → 4 jours
"""

import argparse
import json
import sys
from pathlib import Path

# Permettre l'exécution depuis le dossier MstreamTrader/
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from core import market_data
from core.backtest import Backtest, BacktestConfig


DEFAULT_COIN_IDS = [c["id"] for c in market_data.DEFAULT_COINS]


def parse_args():
    p = argparse.ArgumentParser(
        description="Backtest du Bot Maître sur données historiques CoinGecko",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--days",          type=int,   default=90,
                   help="Nombre de jours d'historique (défaut: 90)")
    p.add_argument("--interval",      type=str,   default="1h",
                   choices=["15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"],
                   help="Granularité des bougies (défaut: 1h, Binance public)")
    p.add_argument("--capital",       type=float, default=1000.0,
                   help="Capital initial en USDT (défaut: 1000)")
    p.add_argument("--coins",         type=str,   default=",".join(DEFAULT_COIN_IDS),
                   help="Coin IDs CoinGecko séparés par virgule")
    p.add_argument("--risk",          type=float, default=5.0,
                   help="Risque par trade en %% du budget (défaut: 5)")
    p.add_argument("--max-positions", type=int,   default=4,
                   help="Positions simultanées max (défaut: 4)")
    p.add_argument("--min-score",     type=float, default=55.0,
                   help="Score minimum pour entrer (défaut: 55)")
    p.add_argument("--min-rr",        type=float, default=2.5,
                   help="Ratio R/R minimum (défaut: 2.5)")
    p.add_argument("--fee",           type=float, default=0.1,
                   help="Frais Binance en %% (défaut: 0.1)")
    p.add_argument("--slippage",      type=float, default=0.05,
                   help="Slippage estimé en %% (défaut: 0.05)")
    p.add_argument("--regime",        action="store_true",
                   help="Activer le filtre de régime Bull/Bear (EMA 200 BTC)")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Afficher le détail de chaque trade")
    p.add_argument("--save",          type=str,
                   help="Sauver le résultat détaillé en JSON")
    return p.parse_args()


def fetch_coins_data(coin_ids: list[str], days: int, interval: str = "1h") -> dict:
    """Télécharge les bougies OHLCV pour chaque coin (Binance public puis CoinGecko fallback)."""
    print(f"Téléchargement de {days} jours d'historique "
          f"(intervalle {interval}) pour {len(coin_ids)} coins...")
    data = {}
    for cid in coin_ids:
        print(f"  - {cid:20} ", end="", flush=True)
        candles = market_data.get_ohlcv_for_analysis(cid, days=days, interval=interval)
        if candles and len(candles) >= 60:
            print(f"{len(candles):>5} bougies")
            data[cid] = candles
        else:
            print(f"  ECHEC ({len(candles) if candles else 0} bougies — seuil min 60)")
    print()
    return data


def detect_candle_granularity(coin_data: dict) -> tuple[int, int]:
    """
    Détecte la granularité moyenne des bougies (en secondes).
    Retourne (candle_duration_sec, periods_per_year).
    """
    all_candles = next(iter(coin_data.values()))
    if len(all_candles) < 2:
        return 4 * 3600, 2190   # 4h par défaut

    diffs = [all_candles[i + 1]["timestamp"] - all_candles[i]["timestamp"]
             for i in range(min(20, len(all_candles) - 1))]
    avg_diff = sum(diffs) / len(diffs)

    # Arrondir à la granularité connue la plus proche
    known = {1800: "30m", 3600: "1h", 14400: "4h", 86400: "1d", 345600: "4d"}
    closest = min(known.keys(), key=lambda x: abs(x - avg_diff))
    periods = int(86400 * 365 / closest)
    return closest, periods


def print_trades(trades: list, coin_lookup: dict):
    """Affiche la liste détaillée des trades."""
    if not trades:
        print("\n[Aucun trade exécuté]\n")
        return

    print("\n" + "─" * 100)
    print(f"  {'#':>3}  {'Coin':<12} {'Entry':>10} → {'Exit':>10}  "
          f"{'Qty':>10}  {'P&L':>+10}  {'R':>+6}  {'Raison':<6}  {'Durée':>6}")
    print("─" * 100)
    for i, t in enumerate(trades, 1):
        coin = t["coin_id"][:12]
        print(f"  {i:>3}  {coin:<12} "
              f"{t['entry_price']:>10.4f} → {t['exit_price']:>10.4f}  "
              f"{t['quantity']:>10.4f}  "
              f"{t['pnl']:>+10.2f}  "
              f"{t['r_multiple']:>+6.2f}  "
              f"{t['exit_reason']:<6}  "
              f"{t['duration']:>6}b")
    print("─" * 100)


def main():
    args = parse_args()
    coin_ids = [c.strip() for c in args.coins.split(",") if c.strip()]

    # 1. Télécharger les données
    coins_data = fetch_coins_data(coin_ids, args.days, args.interval)
    if not coins_data:
        print("ERREUR : aucun historique récupéré. Vérifier la connexion Internet.")
        sys.exit(1)

    # 2. Détecter la granularité
    candle_sec, periods_year = detect_candle_granularity(coins_data)
    print(f"Granularité détectée : ~{candle_sec}s "
          f"({candle_sec//3600}h — {periods_year} périodes/an)\n")

    # 3. Configurer
    config = BacktestConfig(
        initial_capital     = args.capital,
        min_score           = args.min_score,
        min_rr              = args.min_rr,
        risk_pct            = args.risk,
        max_positions       = args.max_positions,
        fee_rate            = args.fee / 100,
        slippage_pct        = args.slippage,
        periods_per_year    = periods_year,
        candle_duration_sec = candle_sec,
        cooldown_candles    = max(1, 21600 // candle_sec),   # ~6h cooldown réel
        use_regime_filter   = args.regime,
    )
    print(f"Configuration :")
    print(f"  Capital initial : ${args.capital:,.2f}")
    print(f"  Risque/trade    : {args.risk}%")
    print(f"  Max positions   : {args.max_positions}")
    print(f"  Score min       : {args.min_score}")
    print(f"  R/R min         : {args.min_rr}")
    print(f"  Frais           : {args.fee}%")
    print(f"  Slippage        : {args.slippage}%")
    print(f"  Cooldown        : {config.cooldown_candles} bougies")
    print(f"  Filtre régime   : {'ON (Bull/Bear adaptatif)' if args.regime else 'OFF (seuils fixes)'}")
    print()

    # 4. Exécuter
    print("Exécution du backtest en cours...")
    bt = Backtest(config)
    result = bt.run(coins_data)

    # 5. Afficher le rapport
    print(result.format_report())
    print()
    print(f"  RÉPARTITION DES SORTIES")
    for reason, count in sorted(result.closed_by_reason.items()):
        label = {"SL": "Stop-Loss touché", "TP": "Take-Profit touché",
                 "END": "Fin de période"}.get(reason, reason)
        print(f"    {label:<22} : {count}")
    print(f"  DURÉE : {result.duration_days:.1f} jours "
          f"({len(result.equity_curve)} bougies)")

    # 6. Détail trades si demandé
    if args.verbose:
        coin_lookup = {c["id"]: c["symbol"] for c in market_data.DEFAULT_COINS}
        print_trades(result.trades, coin_lookup)

    # 7. Sauvegarde JSON
    if args.save:
        payload = {
            "config":           vars(config),
            "report":           result.report,
            "duration_days":    result.duration_days,
            "closed_by_reason": result.closed_by_reason,
            "trades":           result.trades,
            "equity_curve":     result.equity_curve,
        }
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"\nRésultat complet sauvegardé dans : {args.save}")


if __name__ == "__main__":
    main()
