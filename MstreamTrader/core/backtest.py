"""
MstreamTrader - Moteur de Backtesting
=======================================

Simule le comportement du Bot Maître sur données historiques pour
valider la stratégie AVANT de trader en réel.

Principes clés :
    - Portfolio multi-coins simulé, bougies alignées par timestamp
    - Indicateurs recalculés à chaque bougie sur l'historique visible (pas de look-ahead)
    - SL/TP vérifiés intra-candle via High/Low (ordre conservateur : SL en premier)
    - Trailing SL, drawdown pause, cooldown, max positions : tout respecté
    - Fees et slippage modélisés
    - Capital composé (profits réinvestis)

Usage programmatique :
    from core.backtest import Backtest, BacktestConfig
    from core.market_data import get_historical_prices

    coins_data = {
        "bitcoin":  get_historical_prices("bitcoin",  days=90),
        "ethereum": get_historical_prices("ethereum", days=90),
    }
    bt = Backtest(BacktestConfig(initial_capital=1000.0))
    result = bt.run(coins_data)
    print(result.format_report())
"""

from dataclasses import dataclass, field
from typing import Optional

from core import indicators, signals
from core.signals import Signal
from core.metrics import compute_full_report, format_report
from core.regime import Regime, detect_regime, get_profile
# Modules institutional (intégrés dans le backtest pour refléter le bot live)
from core import ensemble as ensemble_mod
from core import correlation as corr_mod
from core import mtf as mtf_mod
from core import position_sizing as ps_mod
from core.circuit_breaker import CircuitBreaker, CircuitConfig, CircuitState


# ─── Configuration ────────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """Paramètres du backtest — reprend la logique MASTER_CONFIG du Bot Maître."""
    initial_capital:          float = 1000.0

    # Filtres de qualification (identiques au Bot Maître réel)
    min_score:                float = 55.0
    min_confidence:           float = 65.0
    min_rr:                   float = 2.5

    # Dimensionnement
    risk_pct:                 float = 5.0
    max_positions:            int   = 4
    max_capital_pct:          float = 80.0

    # Trailing SL
    trailing_activate_pct:    float = 1.5
    trailing_sl_atr_mult:     float = 1.5
    trailing_sl_fallback_pct: float = 2.5

    # Cooldown (en bougies — à convertir selon la granularité)
    cooldown_candles:         int   = 6   # ex: 6 × 4h = 24h, 6 × 1h = 6h

    # Protection
    max_drawdown_pct:         float = 20.0

    # Coûts
    fee_rate:                 float = 0.001   # 0.1 % Binance standard
    slippage_pct:             float = 0.05    # 0.05 % slippage moyen

    # Warmup — bougies nécessaires pour stabiliser les indicateurs (EMA 50)
    warmup_candles:           int   = 60

    # Granularité (pour annualisation des métriques)
    # 6 = 4h candles (6/jour × 365), 24 = 1h candles, 1 = daily
    periods_per_year:         int   = 2190   # 4h par défaut (6 × 365)
    candle_duration_sec:      int   = 4 * 3600

    # Filtre de régime de marché (Bull/Bear/Neutral)
    # Si True, les seuils s'adaptent au régime BTC détecté à chaque bougie
    use_regime_filter:        bool  = False
    regime_ema_period:        int   = 200
    regime_threshold_pct:     float = 2.0

    # ── Modules Institutional Grade (DOIVENT refléter MASTER_CONFIG du bot live) ──
    use_ensemble:             bool  = True    # vote 3 stratégies
    min_ensemble_agreement:   int   = 2       # ≥ 2/3 stratégies d'accord
    min_ensemble_score:       float = 30.0

    use_correlation_block:    bool  = True    # refus si corrélation > seuil
    correlation_threshold:    float = 0.75
    correlation_lookback:     int   = 240     # bougies pour calcul corrélation

    use_mtf_confluence:       bool  = True    # Multi-Timeframe Confluence
    mtf_min_confluence:       int   = 2       # ≥ 2/3 TF alignés

    use_kelly_sizing:         bool  = True    # Kelly Criterion pour taille position
    kelly_fraction:           float = 0.25    # 1/4 Kelly (fractional)
    vol_target_pct:           float = 2.0     # volatility targeting

    # Circuit Breaker (simulé pendant le backtest pour coller au bot live)
    use_circuit_breaker:      bool  = True
    cb_max_consecutive_sl:    int   = 5
    cb_rapid_dd_pct:          float = 10.0
    cb_rapid_dd_hours:        float = 4.0

    # User risk override (cohérence avec le bot live qui lit `risk_master` en DB)
    user_risk_override:       Optional[float] = None


# ─── État simulé ──────────────────────────────────────────────────────────────

@dataclass
class SimPosition:
    """Position ouverte pendant le backtest."""
    coin_id:      str
    entry_idx:    int           # index de la bougie d'entrée
    entry_ts:     float
    entry_price:  float
    quantity:     float
    entry_usdt:   float         # capital engagé
    stop_loss:    float
    take_profit:  float
    initial_risk: float         # (entry − sl) × qty → pour calculer R-multiple


@dataclass
class BacktestResult:
    """Résultat d'un backtest. `report` contient toutes les métriques."""
    trades:       list
    equity_curve: list
    config:       BacktestConfig
    report:       dict
    duration_days: float
    closed_by_reason: dict = field(default_factory=dict)
    regime_distribution: dict = field(default_factory=dict)    # Regime → nb bougies
    trades_by_regime:    dict = field(default_factory=dict)    # Regime → nb trades
    # Tracking des rejets par filtre (même filtres que le bot live)
    rejections_by_filter: dict = field(default_factory=dict)   # "ensemble"/"correlation"/"mtf"/... → count
    signals_analyzed:     int  = 0
    signals_qualified:    int  = 0

    def format_report(self) -> str:
        report = format_report(self.report)
        if self.regime_distribution:
            report += "\n\n  RÉPARTITION PAR RÉGIME DE MARCHÉ"
            total = sum(self.regime_distribution.values())
            for reg_name, count in self.regime_distribution.items():
                pct = count / total * 100 if total > 0 else 0
                tr  = self.trades_by_regime.get(reg_name, 0)
                report += f"\n    {reg_name:<10} : {count:>5} bougies ({pct:>5.1f}%)  {tr:>3} trades"
        if self.rejections_by_filter:
            report += "\n\n  FILTRES DE QUALIFICATION (rejets)"
            report += f"\n    Signaux analyses  : {self.signals_analyzed}"
            report += f"\n    Signaux qualifies : {self.signals_qualified}"
            for filter_name, count in sorted(self.rejections_by_filter.items(),
                                             key=lambda x: -x[1]):
                report += f"\n    rejet {filter_name:<15} : {count:>5}"
        return report


# ─── Moteur ───────────────────────────────────────────────────────────────────

class Backtest:
    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()

    # ─── Point d'entrée public ────────────────────────────────────────────────

    def run(self, coins_data: dict,
            btc_daily_history: Optional[list] = None) -> BacktestResult:
        """
        Lance un backtest.

        coins_data : dict[str, list[dict]]
            coin_id → liste de bougies triées {timestamp, open, high, low, close}

        btc_daily_history : list[dict] optionnel
            Bougies daily BTC (minimum 200) utilisées pour la détection de régime.
            Requis si use_regime_filter=True. Si None et régime activé, fetch automatique
            depuis Binance public klines.
        """
        # Filtrer les coins avec assez de bougies
        valid_coins = {
            cid: candles for cid, candles in coins_data.items()
            if len(candles) >= self.config.warmup_candles + 10
        }
        if not valid_coins:
            raise ValueError("Aucun coin avec assez de données (min "
                             f"{self.config.warmup_candles + 10} bougies)")

        # Timestamps alignés (intersection de tous les timestamps)
        all_timestamps = sorted(set.intersection(*[
            {c["timestamp"] for c in candles} for candles in valid_coins.values()
        ]))

        if len(all_timestamps) < self.config.warmup_candles + 10:
            raise ValueError("Timestamps communs insuffisants après alignement")

        # Index rapide : coin_id → {ts → candle_idx}
        ts_index = {
            cid: {c["timestamp"]: idx for idx, c in enumerate(candles)}
            for cid, candles in valid_coins.items()
        }

        # État simulé
        capital        = self.config.initial_capital
        peak_equity    = capital
        open_positions: dict[str, SimPosition] = {}
        closed_trades  = []
        equity_curve   = []
        cooldown_until: dict[str, float] = {}   # coin_id → ts
        drawdown_pause = False

        # State mutable pour tracker les rejets + cache correlation
        institutional_state: dict = {
            "rejections_by_filter": {},
            "signals_analyzed":     0,
            "signals_qualified":    0,
            "correlation_matrix":   {},
            "corr_last_idx":        -9999,
        }

        # ── Circuit Breaker local (simulé pour le backtest) ──
        # Indispensable pour que les stratégies à "drawdown rapide" soient rejetées
        # comme elles le seraient en prod.
        backtest_cb: Optional[CircuitBreaker] = None
        if self.config.use_circuit_breaker:
            cb_cfg = CircuitConfig(
                max_consecutive_sl   = self.config.cb_max_consecutive_sl,
                rapid_drawdown_pct   = self.config.cb_rapid_dd_pct,
                rapid_drawdown_hours = self.config.cb_rapid_dd_hours,
                total_drawdown_pct   = self.config.max_drawdown_pct,
            )
            backtest_cb = CircuitBreaker(cb_cfg)

        # ── Précalcul de l'ATR pour toutes les bougies de chaque coin ──
        # Optimisation O(N²) → O(N) : évite de recalculer compute_all à chaque
        # trailing SL update. L'ATR d'une bougie ne dépend que des bougies
        # passées, donc précalculable une seule fois par coin.
        atr_cache: dict[str, list] = {}
        for cid, candles in valid_coins.items():
            try:
                highs  = [c["high"]  for c in candles]
                lows   = [c["low"]   for c in candles]
                closes = [c["close"] for c in candles]
                atr_cache[cid] = indicators.atr(highs, lows, closes, period=14)
            except (ValueError, KeyError, IndexError):
                atr_cache[cid] = []

        # Régime : série daily BTC pour calculer l'EMA 200
        btc_daily_series = []   # liste de tuples (timestamp, close) triés par temps
        regime_distribution = {Regime.BULL.value: 0, Regime.NEUTRAL.value: 0, Regime.BEAR.value: 0}
        trades_by_regime    = {Regime.BULL.value: 0, Regime.NEUTRAL.value: 0, Regime.BEAR.value: 0}
        current_regime      = Regime.NEUTRAL

        if self.config.use_regime_filter:
            if btc_daily_history and len(btc_daily_history) >= 200:
                # Utiliser la série daily fournie (idéal : 300+ daily BTC)
                btc_daily_series = [(c["timestamp"], c["close"]) for c in btc_daily_history]
            else:
                # Fetch automatique depuis Binance public klines
                try:
                    from core.market_data import get_binance_klines_public
                    daily_fetched = get_binance_klines_public("bitcoin", interval="1d", limit=500)
                    if daily_fetched and len(daily_fetched) >= 200:
                        btc_daily_series = [(c["timestamp"], c["close"]) for c in daily_fetched]
                except (OSError, ValueError, KeyError, TypeError):
                    # Fetch HTTP peut échouer (URLError, timeout, JSON, etc.)
                    # Fallback : reconstruire depuis les données intraday si possible
                    btc_candles = valid_coins.get("bitcoin")
                    if btc_candles:
                        btc_daily_series = self._build_daily_closes(btc_candles)

        # ── Boucle principale sur les bougies ─────────────────────────────────
        for i, ts in enumerate(all_timestamps):
            # Warmup : accumule les données sans trader
            if i < self.config.warmup_candles:
                equity_curve.append(capital)
                continue

            # Collecter les bougies courantes de chaque coin
            current_candles = {}
            for cid in valid_coins:
                idx = ts_index[cid].get(ts)
                if idx is not None:
                    current_candles[cid] = valid_coins[cid][idx]

            # Détecter le régime courant si activé
            if self.config.use_regime_filter and btc_daily_series:
                # On tronque la série daily jusqu'au timestamp courant
                regime_closes = self._slice_daily_closes(btc_daily_series, ts)
                current_regime, _ = detect_regime(
                    regime_closes,
                    ema_period=self.config.regime_ema_period,
                    threshold_pct=self.config.regime_threshold_pct,
                )
            regime_distribution[current_regime.value] += 1

            # 1. Gérer les sorties sur toutes les positions ouvertes
            # NOTE : le cooldown NE démarre PAS à la sortie (aligné avec bot live).
            # Il démarre à l'ENTRÉE (voir _look_for_entries).
            for cid in list(open_positions.keys()):
                pos = open_positions[cid]
                candle = current_candles.get(cid)
                if not candle:
                    continue
                exit_price, exit_reason = self._check_exit(pos, candle)
                if exit_price is not None:
                    trade = self._close_position(pos, exit_price, exit_reason, ts, i)
                    closed_trades.append(trade)
                    capital += trade["gross_return"]
                    del open_positions[cid]
                    # Reporter le résultat au Circuit Breaker pour détecter les
                    # séries de SL consécutifs
                    if backtest_cb is not None:
                        cb_reason = "EXIT_SL" if exit_reason == "SL" else "EXIT_TP"
                        backtest_cb.report_trade_result(
                            pnl=trade["pnl"], exit_reason=cb_reason,
                        )

            # 2. Vérifier la pause drawdown + CB (après sorties, avant entrées)
            # NOTE : dans le backtest, `capital` = cash libre. Total equity =
            #        capital + invested + unrealized (cohérent avec bot live).
            unrealized = sum(
                (current_candles[p.coin_id]["close"] - p.entry_price) * p.quantity
                for p in open_positions.values()
                if p.coin_id in current_candles
            )
            invested_in_positions = sum(p.entry_usdt for p in open_positions.values())
            total_equity = capital + invested_in_positions + unrealized
            peak_equity  = max(peak_equity, total_equity)
            drawdown_pct = (peak_equity - total_equity) / peak_equity * 100 if peak_equity > 0 else 0.0
            drawdown_pause = drawdown_pct >= self.config.max_drawdown_pct

            # Reporter le capital au Circuit Breaker (détecte rapid DD)
            if backtest_cb is not None:
                backtest_cb.report_capital(total_equity)
                backtest_cb.auto_recover_check()

            # 3. Trailing stop-loss (utilise atr_cache pour O(N) au lieu de O(N²))
            self._update_trailing_stops(open_positions, current_candles,
                                        valid_coins, ts_index, i, atr_cache)

            # 4. Chercher de nouvelles entrées (sauf si drawdown pause OU CB bloquant)
            cb_blocks_entries = (
                backtest_cb is not None and not backtest_cb.can_open_new_positions()
            )
            if cb_blocks_entries:
                self._track_rejection(institutional_state, "circuit_breaker")

            if not drawdown_pause and not cb_blocks_entries:
                new_trades = self._look_for_entries(
                    valid_coins, ts_index, i, ts,
                    capital, open_positions, cooldown_until, current_candles,
                    current_regime,
                    closed_trades, institutional_state,
                )
                # Tracker les trades par régime
                for _ in range(new_trades):
                    trades_by_regime[current_regime.value] += 1
                # Recalcul capital disponible après entrées
                capital = capital - sum(
                    p.entry_usdt for p in open_positions.values() if p.entry_idx == i
                )

            # 5. Enregistrer la courbe d'équité
            unrealized_after = sum(
                (current_candles[p.coin_id]["close"] - p.entry_price) * p.quantity
                for p in open_positions.values()
                if p.coin_id in current_candles
            )
            total_equity = capital + sum(p.entry_usdt for p in open_positions.values()) + unrealized_after
            equity_curve.append(total_equity)

        # ── Fin du backtest : fermer toutes les positions restantes au dernier prix ──
        if open_positions:
            last_ts = all_timestamps[-1]
            for cid, pos in list(open_positions.items()):
                last_candle = current_candles.get(cid)
                if last_candle:
                    trade = self._close_position(pos, last_candle["close"], "END",
                                                 last_ts, len(all_timestamps) - 1)
                    closed_trades.append(trade)
                    capital += trade["gross_return"]
            open_positions.clear()
            equity_curve[-1] = capital

        # ── Rapport final ─────────────────────────────────────────────────────
        duration_sec  = all_timestamps[-1] - all_timestamps[0]
        duration_days = duration_sec / 86400

        report = compute_full_report(
            trades=closed_trades,
            equity_curve=equity_curve,
            initial_capital=self.config.initial_capital,
            final_capital=capital,
            duration_days=duration_days,
            periods_per_year=self.config.periods_per_year,
        )

        # Compter les sorties par raison
        reasons = {}
        for t in closed_trades:
            reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1

        return BacktestResult(
            trades=closed_trades,
            equity_curve=equity_curve,
            config=self.config,
            report=report,
            duration_days=duration_days,
            closed_by_reason=reasons,
            regime_distribution=regime_distribution,
            trades_by_regime=trades_by_regime,
            rejections_by_filter=institutional_state["rejections_by_filter"],
            signals_analyzed=institutional_state["signals_analyzed"],
            signals_qualified=institutional_state["signals_qualified"],
        )

    # ─── Logique de sortie ────────────────────────────────────────────────────

    def _check_exit(self, pos: SimPosition, candle: dict) -> tuple[Optional[float], Optional[str]]:
        """
        Vérifie si SL ou TP a été touché pendant la bougie.
        Ordre conservateur : SL testé en premier (cas pire).
        Applique le slippage + frais sur le prix de sortie.
        """
        low  = candle["low"]
        high = candle["high"]
        slip = self.config.slippage_pct / 100

        if low <= pos.stop_loss:
            # SL touché — prix de sortie = SL avec slippage défavorable (sortie sous le SL)
            exec_price = pos.stop_loss * (1 - slip)
            return exec_price, "SL"

        if high >= pos.take_profit:
            # TP touché — prix de sortie = TP avec slippage défavorable (sortie légèrement sous TP)
            exec_price = pos.take_profit * (1 - slip)
            return exec_price, "TP"

        return None, None

    def _close_position(self, pos: SimPosition, price: float, reason: str,
                         ts: float, candle_idx: int) -> dict:
        """Clôture une position et retourne un dict trade."""
        gross_return = pos.quantity * price                     # USDT reçus de la vente
        fees         = gross_return * self.config.fee_rate      # frais de sortie
        net_return   = gross_return - fees                      # USDT nets reçus

        pnl = net_return - pos.entry_usdt                       # P&L net (inclut frais entrée via entry_usdt)
        r_multiple = pnl / pos.initial_risk if pos.initial_risk > 0 else 0

        return {
            "coin_id":       pos.coin_id,
            "entry_idx":     pos.entry_idx,
            "entry_ts":      pos.entry_ts,
            "entry_price":   pos.entry_price,
            "exit_idx":      candle_idx,
            "exit_ts":       ts,
            "exit_price":    price,
            "quantity":      pos.quantity,
            "entry_usdt":    pos.entry_usdt,
            "gross_return":  net_return,         # net après frais de sortie
            "pnl":           pnl,
            "r_multiple":    r_multiple,
            "exit_reason":   reason,             # "SL" | "TP" | "END"
            "duration":      candle_idx - pos.entry_idx,
        }

    # ─── Trailing stop-loss ───────────────────────────────────────────────────

    def _update_trailing_stops(self, open_positions: dict,
                                current_candles: dict,
                                all_candles: dict,
                                ts_index: dict,
                                current_idx: int,
                                atr_cache: dict):
        """
        Met à jour le SL des positions gagnantes.
        Utilise atr_cache précalculé (O(1) lookup au lieu de O(N) compute_all).
        """
        for cid, pos in open_positions.items():
            candle = current_candles.get(cid)
            if not candle:
                continue
            price = candle["close"]
            gain_pct = (price - pos.entry_price) / pos.entry_price * 100

            if gain_pct < self.config.trailing_activate_pct:
                continue

            # Lookup ATR précalculé (streaming O(1))
            atr_est = None
            ts    = candle["timestamp"]
            idx   = ts_index[cid].get(ts)
            if idx is not None:
                atr_list = atr_cache.get(cid, [])
                if 0 <= idx < len(atr_list):
                    val = atr_list[idx]
                    if val is not None and val > 0:
                        atr_est = val

            if atr_est:
                new_sl = price - self.config.trailing_sl_atr_mult * atr_est
            else:
                new_sl = price * (1 - self.config.trailing_sl_fallback_pct / 100)

            if new_sl > pos.stop_loss:
                pos.stop_loss = new_sl

    # ─── Logique d'entrée (reflète EXACTEMENT le bot live) ───────────────────

    def _look_for_entries(self, all_candles: dict, ts_index: dict,
                          current_idx: int, ts: float,
                          capital: float, open_positions: dict,
                          cooldown_until: dict, current_candles: dict,
                          regime: Regime,
                          closed_trades: list,
                          state: dict) -> int:
        """
        Applique les MÊMES filtres que le bot live, dans le MÊME ordre :
          1. Qualification signal (score / conf / R/R selon profil régime)
          2. Ensemble voting (3 stratégies)
          3. Correlation block (> 0.75 avec positions ouvertes)
          4. Multi-Timeframe Confluence (1h + 4h + 1d reconstitués)
          5. Kelly Criterion sizing (ou cold start si < 10 trades simulés)

        Retourne le nombre de nouvelles positions ouvertes.
        `state` : dict mutable contenant rejections_by_filter, signals_analyzed,
                  signals_qualified — pour remplir BacktestResult à la fin.
        """
        cfg = self.config

        profile = get_profile(regime) if cfg.use_regime_filter else {
            "min_score":       cfg.min_score,
            "min_confidence":  cfg.min_confidence,
            "min_rr":          cfg.min_rr,
            "risk_pct":        cfg.risk_pct,
            "max_positions":   cfg.max_positions,
            "max_capital_pct": cfg.max_capital_pct,
        }

        # User override (cohérent avec le bot live qui lit `risk_master` en DB)
        if cfg.user_risk_override is not None and cfg.user_risk_override > 0:
            profile["risk_pct"] = cfg.user_risk_override

        if len(open_positions) >= profile["max_positions"]:
            return 0

        invested = sum(p.entry_usdt for p in open_positions.values())
        total_budget = capital + invested
        max_invest = total_budget * profile["max_capital_pct"] / 100
        if invested >= max_invest:
            return 0

        already_holds = set(open_positions.keys())

        # ── Matrice de corrélation (recalculée périodiquement — au plus toutes les 24 bougies) ──
        if cfg.use_correlation_block and already_holds:
            if state.get("corr_last_idx", -9999) + 24 < current_idx:
                # Rebuild sur la lookback window — utilise les candles déjà en mémoire (pas de HTTP)
                coins_slice = {}
                for cid, candles in all_candles.items():
                    idx = ts_index[cid].get(ts)
                    if idx is None:
                        continue
                    start = max(0, idx - cfg.correlation_lookback)
                    coins_slice[cid] = candles[start:idx + 1]
                if len(coins_slice) >= 2:
                    state["correlation_matrix"] = corr_mod.compute_correlation_matrix(coins_slice)
                    state["corr_last_idx"] = current_idx
        correlation_matrix = state.get("correlation_matrix", {})

        # ── Stats historiques Kelly (basées sur les trades SIMULÉS du backtest) ──
        if cfg.use_kelly_sizing:
            hist_stats = self._compute_backtest_kelly_stats(closed_trades)
        else:
            hist_stats = None

        # ── Filtrage candidats ──
        candidates = []
        for cid, candles in all_candles.items():
            if cid in already_holds:
                self._track_rejection(state, "already_holds")
                continue
            if cooldown_until.get(cid, 0) > ts:
                self._track_rejection(state, "cooldown")
                continue

            idx = ts_index[cid].get(ts)
            if idx is None or idx < 30:
                self._track_rejection(state, "warmup_insufficient")
                continue

            subset = candles[:idx + 1]
            try:
                indics = indicators.compute_all(subset)
            except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
                continue
            if not indics:
                continue

            indics["current_price"] = candles[idx]["close"]
            ts_signal = signals.analyze(cid, cid[:4].upper(), indics)

            state["signals_analyzed"] = state.get("signals_analyzed", 0) + 1

            # Filtre 1 : qualification selon profil régime
            if not self._qualifies(ts_signal, profile):
                self._track_rejection(state, "profile")
                continue

            # Filtre 2 : Ensemble voting
            if cfg.use_ensemble:
                ens_decision = ensemble_mod.vote(cid, indics, regime=regime.value)
                if not ensemble_mod.is_ensemble_qualified(
                    ens_decision,
                    min_agreement=cfg.min_ensemble_agreement,
                    min_score=cfg.min_ensemble_score,
                ):
                    self._track_rejection(state, "ensemble")
                    continue

            # Filtre 3 : Correlation block
            if (cfg.use_correlation_block and correlation_matrix and already_holds):
                too_corr, offender, corr_val = corr_mod.is_too_correlated(
                    correlation_matrix, cid, already_holds,
                    threshold=cfg.correlation_threshold,
                )
                if too_corr:
                    self._track_rejection(state, "correlation")
                    continue

            # Filtre 4 : Multi-Timeframe Confluence
            # IMPORTANT : skip le filtre si < 3 TF disponibles (backtest courts <30j).
            # Évite une sur-stricture : bot live a toujours 3 TF → 2/3 requis (66%).
            # Backtest avec 2 TF exigerait 2/2 (100%) ce qui diverge du bot live.
            if cfg.use_mtf_confluence:
                mtf_result = self._build_mtf_from_1h(candles, idx, cid)
                if mtf_result is not None and len(mtf_result.timeframes) >= 3:
                    if not mtf_mod.is_confluence_valid_for_long(
                        mtf_result, min_confluence=cfg.mtf_min_confluence
                    ):
                        self._track_rejection(state, "mtf")
                        continue
                elif mtf_result is not None and len(mtf_result.timeframes) < 3:
                    # Tracker les cas où MTF a été skip (pour visibilité au user)
                    self._track_rejection(state, "mtf_skipped_insufficient_tf")

            state["signals_qualified"] = state.get("signals_qualified", 0) + 1
            # Attacher les indicateurs pour le Kelly sizing en aval (pas besoin de recalculer)
            candidates.append((ts_signal, indics))

        candidates.sort(key=lambda c: (c[0].score, c[0].risk_reward or 0), reverse=True)

        slots_left = profile["max_positions"] - len(open_positions)
        available  = min(capital, max_invest - invested)
        opened     = 0

        for sig, indics in candidates[:slots_left]:
            # ── Kelly sizing (ou cold start) ──
            if cfg.use_kelly_sizing and hist_stats:
                if hist_stats.get("is_defaults"):
                    # Cold start : 1% du budget, plafond $50 (cohérent bot live)
                    amount_usdt = min(total_budget * 0.01, 50.0)
                else:
                    atr_val = indics.get("atr") or 0
                    vol_pct = (atr_val / sig.price * 100) if sig.price > 0 else 2.0
                    sizing = ps_mod.optimal_position_size(
                        capital               = total_budget,
                        win_rate              = hist_stats["win_rate"],
                        avg_win               = hist_stats["avg_win"],
                        avg_loss              = hist_stats["avg_loss"],
                        entry_price           = sig.price,
                        stop_loss             = sig.stop_loss,
                        realized_vol_pct      = vol_pct,
                        max_risk_per_trade    = profile["risk_pct"],
                        max_position_pct      = profile["max_capital_pct"],
                        kelly_fraction_used   = cfg.kelly_fraction,
                        vol_target_pct        = cfg.vol_target_pct,
                    )
                    amount_usdt = sizing["size_usdt"]
            else:
                amount_usdt = total_budget * profile["risk_pct"] / 100

            if amount_usdt <= 0 or amount_usdt > available or available < 10.0:
                self._track_rejection(state, "sizing_insufficient")
                continue

            exec_price = sig.price * (1 + cfg.slippage_pct / 100)
            fee        = amount_usdt * cfg.fee_rate
            quantity   = (amount_usdt - fee) / exec_price if exec_price > 0 else 0

            if quantity <= 0:
                continue

            initial_risk = (exec_price - sig.stop_loss) * quantity
            if initial_risk <= 0:
                self._track_rejection(state, "invalid_sl")
                continue

            pos = SimPosition(
                coin_id      = sig.coin_id,
                entry_idx    = current_idx,
                entry_ts     = ts,
                entry_price  = exec_price,
                quantity     = quantity,
                entry_usdt   = amount_usdt,
                stop_loss    = sig.stop_loss,
                take_profit  = sig.take_profit,
                initial_risk = initial_risk,
            )
            open_positions[sig.coin_id] = pos
            # Cooldown démarre à l'ENTRÉE (aligné avec bot live is_in_cooldown)
            cooldown_until[sig.coin_id] = ts + cfg.cooldown_candles * cfg.candle_duration_sec
            available -= amount_usdt
            opened    += 1

        return opened

    @staticmethod
    def _track_rejection(state: dict, filter_name: str):
        d = state.setdefault("rejections_by_filter", {})
        d[filter_name] = d.get(filter_name, 0) + 1

    @staticmethod
    def _compute_backtest_kelly_stats(closed_trades: list,
                                       min_trades: int = 10) -> dict:
        """
        Équivalent de position_sizing.compute_historical_stats() mais basé sur
        les trades SIMULÉS du backtest courant (pas la DB).
        Rend le backtest PORTABLE et self-contained.
        """
        if len(closed_trades) < min_trades:
            return {"win_rate": 0.45, "avg_win": 20.0, "avg_loss": 10.0,
                    "sample_size": len(closed_trades), "is_defaults": True}
        wins   = [t["pnl"] for t in closed_trades if t.get("pnl", 0) > 0]
        losses = [-t["pnl"] for t in closed_trades if t.get("pnl", 0) < 0]
        if not wins or not losses:
            return {"win_rate": 0.50,
                    "avg_win":  sum(wins)/len(wins) if wins else 10.0,
                    "avg_loss": sum(losses)/len(losses) if losses else 10.0,
                    "sample_size": len(closed_trades), "is_defaults": True}
        return {
            "win_rate":    len(wins) / len(closed_trades),
            "avg_win":     sum(wins) / len(wins),
            "avg_loss":    sum(losses) / len(losses),
            "sample_size": len(closed_trades),
            "is_defaults": False,
        }

    def _build_mtf_from_1h(self, candles_1h: list, current_idx: int,
                            coin_id: str) -> 'Optional[mtf_mod.MTFConfluence]':
        """
        Reconstitue les bougies 4h et 1d à partir des 1h disponibles,
        puis analyse la confluence. Pas de HTTP — 100 % basé sur les données du backtest.
        """
        if current_idx < 30 or len(candles_1h) < current_idx + 1:
            return None
        visible = candles_1h[:current_idx + 1]

        # Bucketing 4h et 1d par timestamp (floor)
        def bucket(candles, bucket_sec):
            buckets = {}
            for c in candles:
                key = int(c["timestamp"] // bucket_sec) * bucket_sec
                if key not in buckets:
                    buckets[key] = {"timestamp": key,
                                    "open": c["open"], "high": c["high"],
                                    "low": c["low"], "close": c["close"]}
                else:
                    buckets[key]["high"]  = max(buckets[key]["high"],  c["high"])
                    buckets[key]["low"]   = min(buckets[key]["low"],   c["low"])
                    buckets[key]["close"] = c["close"]
            return [buckets[k] for k in sorted(buckets.keys())]

        candles_4h = bucket(visible, 4 * 3600)
        candles_1d = bucket(visible, 86400)

        candles_by_tf = {"1h": visible}
        if len(candles_4h) >= 30:
            candles_by_tf["4h"] = candles_4h
        if len(candles_1d) >= 30:
            candles_by_tf["1d"] = candles_1d

        try:
            return mtf_mod.analyze_confluence(coin_id, candles_by_tf)
        except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
            return None

    def _qualifies(self, sig, profile: dict) -> bool:
        """Filtre paramétré par un profil (régime-adaptatif ou fixe)."""
        if sig.signal is not Signal.STRONG_BUY:
            return False
        if sig.score < profile["min_score"]:
            return False
        if sig.confidence < profile["min_confidence"]:
            return False
        if sig.risk_reward is None or sig.risk_reward < profile["min_rr"]:
            return False
        return True

    # ─── Helpers régime ──────────────────────────────────────────────────────

    @staticmethod
    def _build_daily_closes(hourly_candles: list) -> list:
        """
        Transforme des bougies intraday en une série de clôtures daily
        (une clôture par tranche de 86400 s). Utilisé pour calculer l'EMA 200 daily.
        Retourne liste de (timestamp_epoch, close).
        """
        if not hourly_candles:
            return []
        buckets: dict[int, tuple[float, float]] = {}   # day_bucket → (last_ts, close)
        for c in hourly_candles:
            day = int(c["timestamp"] // 86400)
            ts = c["timestamp"]
            if day not in buckets or ts > buckets[day][0]:
                buckets[day] = (ts, c["close"])
        # Liste triée par jour
        return [(day * 86400, close) for day, (_, close) in sorted(buckets.items())]

    @staticmethod
    def _slice_daily_closes(daily_series: list, ts: float) -> list[float]:
        """Retourne les closes daily disponibles jusqu'à un timestamp donné."""
        return [close for d_ts, close in daily_series if d_ts <= ts]
