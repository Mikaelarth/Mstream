"""
MstreamTrader - Bot Maître : Moteur de Trading Institutional Grade
=====================================================================

Le bot est le maître du jeu. Il dispose d'un budget propre,
prend toutes les décisions de trading de manière autonome,
et fait fructifier son capital par réinvestissement des profits.

Features niveau institutional intégrées :
  1. Régime-aware (Bull/Bear/Neutral via EMA 200 BTC) + détection transition
  2. Circuit Breaker multi-niveaux (HEALTHY/WARNING/TRIGGERED/FROZEN)
  3. Kelly Criterion Fractional + Volatility Targeting (position sizing optimal)
  4. Dynamic Correlation Matrix (refuse les positions trop corrélées)
  5. Ensemble Voting : 3 sous-stratégies votent (trend/reversion/breakout)
  6. Multi-Timeframe Confluence (1h+4h+1d doivent s'aligner)
  7. Audit Trail structuré (traçabilité institutional de chaque décision)
  8. Health Checks continu (API Binance, latence, cohérence données)
  9. Checkpointing (recovery après crash)
  10. Trailing SL adaptatif (ATR-based)

Cycle d'analyse toutes les 60 min — thread daemon indépendant.
Les anciens portefeuilles Sécurité / Libre sont maintenus pour compatibilité.
"""

import threading
import logging
import time
import uuid
from datetime import datetime
from typing import Optional

from core import database, exchange
from core.signals import Signal
from core.regime import Regime, detect_regime, detect_regime_transition, \
                         get_profile, describe as describe_regime
# Modules institutional grade
from core.circuit_breaker import get_circuit_breaker, CircuitState
from core import audit
from core import position_sizing as ps
from core import correlation as corr
from core import ensemble
from core import mtf
from core import checkpoint
from core.health import get_health_checker
from core.adaptive import get_adaptive_agent
from core import notifications
from core import paper_mode

logger = logging.getLogger("bot_maitre")

# ─── Configuration Bot Maître ─────────────────────────────────────────────────

MASTER_CONFIG = {
    "name":                  "Bot Maître",
    "portfolio_type":        "master",
    # Filtres de qualification (écrasés par le profil régime si régime actif)
    "min_score":             55,
    "min_confidence":        65.0,
    "min_rr":                2.5,
    # Dimensionnement
    "risk_pct":              5.0,       # % du budget par position (défaut)
    "max_positions":         4,
    "max_capital_pct":       80.0,
    # Trailing & cooldown
    "cooldown_hours":        6,
    "trailing_activate_pct": 1.5,
    "trailing_sl_atr_mult":  1.5,
    "trailing_sl_fallback_pct": 2.5,
    # Protection
    "max_drawdown_pct":      20.0,
    # Sélection coins
    "allowed_coins":         None,
    # Clés DB
    "budget_key":            "budget_master",
    "initial_key":           "budget_master_initial",
    "active_key":            "auto_trade_master",
    "risk_key":              "risk_master",
    # ── Institutional Grade ──
    "correlation_threshold": 0.75,      # refuse si corrélation > 0.75 avec positions ouvertes
    "correlation_lookback_candles": 240, # ~10 jours en 1h
    "kelly_fraction":        0.25,      # Kelly fractional (1/4 de full Kelly)
    "vol_target_pct":        2.0,       # volatility cible en %
    "min_ensemble_agreement": 2,        # min 2/3 stratégies d'accord
    "min_ensemble_score":    30.0,
    "use_ensemble":          True,      # activer le vote d'ensemble
    "use_correlation_block": True,      # activer le blocage par corrélation
    "use_kelly_sizing":      True,      # activer Kelly pour la taille de position
    "use_mtf_confluence":    True,      # activer multi-timeframe (1h+4h+1d)
    "mtf_min_confluence":    2,         # min TFs alignés haussier
    "use_regime_transition": True,      # adapter profil selon transition détectée
    # ── Apprentissage adaptatif (Thompson + UCB + Memory) ──
    "use_adaptive":          True,      # activer l'agent adaptatif
    "adaptive_min_trades":   10,        # min trades avant de faire confiance au bandit
    # ── Partial Exits (TP1 50 % + runner break-even) ──
    "use_partial_exits":     True,      # activer les partial exits
    "partial_exit_fraction": 0.5,       # part vendue au TP1 (0.5 = 50 %)
    # Checkpointing / Health
    "checkpoint_every_n_cycles": 6,     # snapshot toutes les 6 heures (si cycle=1h)
    "health_check_every_n_cycles": 1,   # health check chaque cycle
    "audit_purge_every_n_cycles": 24,   # purge une fois par jour
    "audit_keep_days":        30,
    "db_backup_every_n_cycles": 24,     # backup DB toutes les 24 cycles (~24h)
    "db_backup_retention_days": 7,      # garde 7 jours de backups
}

# ─── Anciens portefeuilles (compatibilité) ────────────────────────────────────

LEGACY_PORTFOLIOS: dict[str, dict] = {
    "securite": {
        "name":           "Sécurité",
        "min_score":      60,
        "min_confidence": 75.0,
        "min_rr":         3.0,
        "risk_pct":       1.0,
        "max_positions":  3,
        "allowed_coins":  {"bitcoin", "ethereum", "binancecoin", "solana", "ripple"},
        "cooldown_hours": 24,
        "budget_key":     "budget_securite",
        "active_key":     "auto_trade_securite",
        "risk_key":       None,
    },
    "libre": {
        "name":           "Libre",
        "min_score":      50,
        "min_confidence": 60.0,
        "min_rr":         2.0,
        "risk_pct":       3.0,
        "max_positions":  5,
        "allowed_coins":  None,
        "cooldown_hours": 4,
        "budget_key":     "budget_libre",
        "active_key":     "auto_trade_libre",
        "risk_key":       "risk_libre",
    },
}

CYCLE_INTERVAL  = 3600  # 60 min — aligné avec la granularité 1h/4h des données d'analyse
STARTUP_DELAY   = 45    # laisser le dashboard charger au démarrage
DATA_MAX_AGE    = 3900  # 65 min avant de fetch les données en autonome (> un cycle)


class AutoTrader:
    """
    Bot Maître — moteur de trading entièrement autonome.
    Démarre via start() ; les données marché sont injectées par update_market_data()
    ou fetchées en autonome si les données injectées sont trop anciennes.
    """

    def __init__(self):
        self._thread:          Optional[threading.Thread] = None
        self._stop_event       = threading.Event()
        self._lock             = threading.Lock()
        self._latest_signals:  list  = []
        self._latest_prices:   dict  = {}
        self._data_timestamp:  float = 0.0
        self._status           = "En attente du premier cycle…"
        # Régime de marché (caché, refreshed toutes les 6 h)
        self._regime:          Regime   = Regime.NEUTRAL
        self._regime_deviation: Optional[float] = None
        self._regime_ts:       float    = 0.0
        self._regime_ttl:      float    = 6 * 3600    # 6 h entre 2 détections
        self._regime_transition: dict   = {}           # dernier résultat de detect_regime_transition
        # Tracking pour notifications (évite les doublons à chaque cycle)
        self._last_cb_state_notified: Optional[str] = None
        self._drawdown_pause_notified: bool = False
        # Daily summary : déclenché 1× par jour calendaire
        self._last_daily_summary_day: Optional[int] = None
        # Compteur de cycles (pour planning checkpoint / health / purge)
        self._cycle_count:     int      = 0
        # Cache daily BTC (pour régime + transition)
        self._btc_daily_cache: list     = []
        self._btc_daily_ts:    float    = 0.0
        # Cache OHLCV par cycle : dédoublonne les fetches HTTP dans un même cycle
        # (correlation/ensemble/mtf/kelly peuvent fetch le même coin×interval)
        # Réinitialisé au début de chaque cycle.
        self._cycle_ohlcv_cache: dict    = {}

    # ─── Cycle de vie ─────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        # Activer l'audit logger async (worker thread dédié pour les INSERTs)
        try:
            audit.enable_async_audit()
        except (ImportError, AttributeError) as exc:
            logger.warning(f"[BotMaitre] Audit async non démarré : {exc}")

        # Auto-recovery : restaurer le dernier snapshot si < 24h
        try:
            from core.checkpoint import auto_recover_on_startup
            recovered = auto_recover_on_startup()
            if recovered:
                logger.info("[BotMaitre] Snapshot récupéré, état volatile restauré")
        except (ImportError, AttributeError, KeyError) as exc:
            logger.warning(f"[BotMaitre] Echec auto-recovery : {exc}")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="BotMaitre"
        )
        self._thread.start()
        logger.info("[BotMaitre] Démarré")

    def stop(self):
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_status(self) -> str:
        return self._status

    # ─── Injection des données depuis DashboardScreen ─────────────────────────

    def update_market_data(self, prices: dict, signals: list):
        import time
        with self._lock:
            self._latest_prices   = dict(prices)
            self._latest_signals  = list(signals)
            self._data_timestamp  = time.time()

    # ─── Boucle principale ────────────────────────────────────────────────────

    def _run_loop(self):
        self._stop_event.wait(STARTUP_DELAY)
        while not self._stop_event.is_set():
            try:
                self._cycle()
            except Exception as exc:
                logger.error(f"[BotMaitre] Erreur cycle: {exc}")
                self._status = f"Erreur: {exc}"
            self._stop_event.wait(CYCLE_INTERVAL)

    def _cycle(self):
        import time
        now = datetime.now()
        self._cycle_count += 1
        self._status = f"Analyse… {now.strftime('%H:%M:%S')}"

        # Reset du cache OHLCV : chaque cycle repart de zéro (évite les données périmées)
        self._cycle_ohlcv_cache = {}

        with self._lock:
            signals    = list(self._latest_signals)
            prices     = dict(self._latest_prices)
            data_age   = time.time() - self._data_timestamp

        # Fetch autonome si les données injectées sont trop vieilles ou absentes
        if data_age > DATA_MAX_AGE or not signals or not prices:
            logger.info("[BotMaitre] Fetch autonome des données marché")
            prices, signals = self._fetch_own_data()

        if not prices or not signals:
            self._status = "En attente des données marché…"
            return

        # ── Tâches périodiques (health / checkpoint / purge audit) ────────────
        self._run_periodic_tasks(prices, signals)

        # ── Bot Maître ─────────────────────────────────────────────────────────
        master_active = (
            database.get_setting(MASTER_CONFIG["active_key"], "false") == "true"
        )
        # Budget : résolu selon paper_mode (master vs master_paper)
        master_budget = float(database.get_setting(self._resolved_budget_key(), "0"))

        if master_active:
            if master_budget <= 0:
                self._status = "BOT MAÎTRE: Budget non configuré — définissez un budget"
            elif self._check_drawdown(master_budget):
                self._status = (
                    f"BOT MAÎTRE: Drawdown max atteint ({MASTER_CONFIG['max_drawdown_pct']}%) "
                    f"— Trading suspendu"
                )
                database.log_auto_trader(
                    "master", "PAUSE", "", "", 0, 0,
                    f"Drawdown max {MASTER_CONFIG['max_drawdown_pct']}% atteint"
                )
                # Notification Telegram (une seule fois jusqu'au reset du flag)
                if not self._drawdown_pause_notified:
                    initial = float(database.get_setting(self._resolved_initial_key(), "0"))
                    dd_pct = ((initial - master_budget) / initial * 100) if initial > 0 else 0
                    notifications.notify_drawdown_pause(
                        drawdown_pct=dd_pct,
                        max_allowed=MASTER_CONFIG["max_drawdown_pct"],
                    )
                    self._drawdown_pause_notified = True
            else:
                # Reset le flag dès que le drawdown se résorbe + cycle normal
                self._drawdown_pause_notified = False
                self._run_master_cycle(prices, signals, master_budget)

        # ── Anciens portefeuilles (compatibilité) ──────────────────────────────
        for ptype, cfg in LEGACY_PORTFOLIOS.items():
            if database.get_setting(cfg["active_key"], "false") != "true":
                continue
            budget = float(database.get_setting(cfg["budget_key"], "0"))
            if budget <= 0:
                continue
            config = dict(cfg)
            if cfg.get("risk_key"):
                config["risk_pct"] = float(
                    database.get_setting(cfg["risk_key"], str(cfg["risk_pct"]))
                )
            self._manage_exits(ptype, config, prices)
            self._look_for_entries(ptype, config, signals, prices, budget)

    # ─── Cycle Bot Maître ─────────────────────────────────────────────────────

    def _run_master_cycle(self, prices: dict, signals: list, budget: float):
        # ID unique pour regrouper tous les logs audit de ce cycle
        cycle_id = f"cycle-{int(time.time())}-{uuid.uuid4().hex[:6]}"

        # 0. Rafraîchir le régime si TTL expiré
        self._refresh_regime_if_stale(cycle_id=cycle_id)

        # 0.5. Vérifier le circuit breaker + notification sur transition d'état
        cb = get_circuit_breaker()
        cb.auto_recover_check()
        cb_state_now = cb.get_state().value
        if self._last_cb_state_notified != cb_state_now:
            # Notifier seulement les transitions importantes (vers TRIGGERED ou FROZEN)
            # ou vers HEALTHY après une alerte
            if cb_state_now in ("triggered", "frozen") or (
                self._last_cb_state_notified in ("triggered", "frozen", "warning")
                and cb_state_now == "healthy"
            ):
                notifications.notify_circuit_breaker(
                    state=cb_state_now.upper(),
                    message=cb.get_status_message(),
                )
            self._last_cb_state_notified = cb_state_now

        # Capital courant total (pour report drawdown au circuit breaker)
        # IMPORTANT : budget_master contient DÉJÀ tout le capital (l'argent investi
        # n'est pas soustrait tant qu'on ne clôture pas). On ajoute SEULEMENT le
        # P&L latent des positions ouvertes. Pas de double-comptage.
        # Portfolio résolu selon paper_mode.
        open_pos = database.get_open_positions(self._resolved_portfolio_type())
        unrealized = sum(
            (prices.get(p["coin_id"], {}).get("price", p["entry_price"]) - p["entry_price"])
            * p["quantity"]
            for p in open_pos
        )
        total_equity = budget + unrealized
        cb.report_capital(total_equity)

        if not cb.can_manage_exits():
            self._status = f"BOT MAITRE GELE — {cb.get_status_message()}"
            audit.log_event(audit.AuditEvent(
                event_type="CIRCUIT_BREAKER", decision="FROZEN",
                severity="critical",
                reasoning=[f"Bot gele : {cb.get_status_message()}"],
                cycle_id=cycle_id,
            ))
            return

        # 1. Trailing stops + exits (toujours autorisés sauf FROZEN)
        self._update_trailing_stops(prices, signals)
        exits_count = self._manage_master_exits(prices, cycle_id=cycle_id)

        # 2. Entrées (seulement si circuit HEALTHY ou WARNING)
        entries_count = 0
        if cb.can_open_new_positions():
            entries_count = self._look_for_master_entries_advanced(
                signals, prices, budget, cycle_id=cycle_id
            )
        else:
            audit.log_event(audit.AuditEvent(
                event_type="CIRCUIT_BREAKER", decision="NO_NEW_ENTRIES",
                severity="warning",
                reasoning=[f"Entrees bloquees : {cb.get_status_message()}"],
                cycle_id=cycle_id,
            ))

        # 3. Stats + status (résolus selon paper_mode)
        ptype_resolved = self._resolved_portfolio_type()
        open_count = len(database.get_open_positions(ptype_resolved))
        budget_now = float(database.get_setting(self._resolved_budget_key(), "0"))
        roi        = self._compute_roi()
        regime_label = self._regime.value.upper()
        cb_label = cb.get_state().value.upper()
        now = datetime.now()
        self._status = (
            f"BOT MAITRE [{regime_label}/{cb_label}] | Capital: ${budget_now:,.2f} | "
            f"ROI: {roi:+.1f}% | Positions: {open_count} | {now.strftime('%H:%M')}"
        )

        audit.log_cycle_completed(
            cycle_id=cycle_id,
            regime=self._regime.value,
            positions_open=open_count,
            capital=budget_now,
            new_entries=entries_count,
            exits=exits_count,
        )

    # ─── Détection du régime de marché ────────────────────────────────────────

    # ─── Helpers de résolution mode (paper vs réel) ───────────────────────────

    def _resolved_portfolio_type(self) -> str:
        """Retourne 'master' ou 'master_paper' selon le mode courant."""
        return paper_mode.get_portfolio_type("master")

    def _resolved_budget_key(self) -> str:
        """Retourne la clé budget courante (master vs master_paper)."""
        return paper_mode.get_budget_key()

    def _resolved_initial_key(self) -> str:
        """Retourne la clé capital initial courante."""
        return paper_mode.get_initial_key()

    def _refresh_regime_if_stale(self, cycle_id: str = None):
        """
        Détecte le régime BTC + analyse transition si la dernière détection
        date de plus de 6 h. Met aussi à jour le cache daily BTC.
        """
        now = time.time()
        if (now - self._regime_ts) < self._regime_ttl:
            return

        old_regime = self._regime
        try:
            from core.market_data import get_binance_klines_public
            daily = get_binance_klines_public("bitcoin", interval="1d", limit=500)
            if daily and len(daily) >= 200:
                closes = [c["close"] for c in daily]
                self._btc_daily_cache = daily
                self._btc_daily_ts    = now
                self._regime, self._regime_deviation = detect_regime(closes)
                self._regime_ts = now

                # Détection transition (signal avancé)
                if MASTER_CONFIG.get("use_regime_transition", True):
                    self._regime_transition = detect_regime_transition(closes)
                    if self._regime_transition.get("transitioning"):
                        logger.info(
                            f"[BotMaitre] Transition regime detectee : "
                            f"{self._regime_transition['from_regime']} -> "
                            f"{self._regime_transition['to_regime']} "
                            f"(score={self._regime_transition['transition_score']})"
                        )

                logger.info(f"[BotMaitre] Régime détecté : "
                            f"{describe_regime(self._regime, self._regime_deviation)}")
                get_circuit_breaker().report_api_success()

                if old_regime != self._regime:
                    audit.log_regime_change(
                        old_regime=old_regime.value,
                        new_regime=self._regime.value,
                        deviation_pct=self._regime_deviation or 0.0,
                        cycle_id=cycle_id,
                    )
            else:
                logger.info("[BotMaitre] Régime : données daily insuffisantes (fallback NEUTRAL)")
        except Exception as exc:
            logger.warning(f"[BotMaitre] Échec détection régime : {exc}")
            get_circuit_breaker().report_api_error(str(exc))

    def get_regime(self) -> tuple[Regime, Optional[float]]:
        """Retourne le régime actuel pour affichage UI."""
        return self._regime, self._regime_deviation

    # ─── Tâches périodiques (health / checkpoint / purge) ────────────────────

    def _run_periodic_tasks(self, prices: dict, signals: list):
        """Lance les checks et maintenances périodiques selon le cycle_count."""
        # Health check
        if self._cycle_count % MASTER_CONFIG["health_check_every_n_cycles"] == 0:
            try:
                health = get_health_checker()
                # Échantillon de bougies pour sanity check
                sample = None
                try:
                    sample = self._cached_ohlcv("bitcoin", days=1, interval="1h")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    logger.warning(f"[BotMaitre] Health sample fetch failed: {exc}")
                health.run_full_check(
                    data_timestamp=self._data_timestamp,
                    sample_candles=sample,
                )
            except Exception as exc:
                logger.warning(f"[BotMaitre] Health check failed : {exc}")

        # Checkpoint
        if self._cycle_count % MASTER_CONFIG["checkpoint_every_n_cycles"] == 0:
            try:
                snap = checkpoint.capture_current_state()
                checkpoint.save_snapshot(snap, keep_last_n=20)
                logger.info(f"[BotMaitre] Snapshot sauvegarde "
                            f"(cycle #{self._cycle_count})")
            except Exception as exc:
                logger.warning(f"[BotMaitre] Checkpoint failed : {exc}")

        # Purge audit ancienne
        if self._cycle_count % MASTER_CONFIG["audit_purge_every_n_cycles"] == 0:
            try:
                removed = audit.purge_old_events(
                    days=MASTER_CONFIG["audit_keep_days"]
                )
                if removed:
                    logger.info(f"[BotMaitre] Audit purge : {removed} evenements supprimes")
            except (ImportError, ValueError, KeyError) as exc:
                logger.warning(f"[BotMaitre] Audit purge failed : {exc}")

        # Backup DB quotidien (atomique + purge rétention 7 jours)
        if self._cycle_count % MASTER_CONFIG["db_backup_every_n_cycles"] == 0:
            try:
                from core.backup import create_backup_and_purge
                backup_path = create_backup_and_purge(
                    retention_days=MASTER_CONFIG["db_backup_retention_days"]
                )
                if backup_path:
                    logger.info(f"[BotMaitre] DB backup : {backup_path.name}")
            except (ImportError, OSError) as exc:
                logger.warning(f"[BotMaitre] DB backup failed : {exc}")

        # Daily summary Telegram (1 fois par jour calendaire)
        try:
            today = int(time.time() // 86400)
            if (self._last_daily_summary_day is not None
                and today != self._last_daily_summary_day):
                self._send_daily_summary()
            if self._last_daily_summary_day is None:
                # Premier cycle : on initialise sans envoyer (pas de stats encore)
                self._last_daily_summary_day = today
            else:
                self._last_daily_summary_day = today
        except (ValueError, KeyError) as exc:
            logger.warning(f"[BotMaitre] Daily summary check failed : {exc}")

    def _send_daily_summary(self):
        """Envoie le résumé Telegram du jour précédent (P&L, trades, ROI)."""
        try:
            from datetime import datetime, timedelta
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            ptype = self._resolved_portfolio_type()
            with database.get_connection() as conn:
                # Trades fermés hier
                rows = conn.execute(
                    """SELECT pnl FROM (
                         SELECT (t.price - op.entry_price) * t.quantity AS pnl
                         FROM trades t JOIN open_positions op
                           ON t.coin_id = op.coin_id AND op.portfolio_type = ?
                         WHERE t.side='SELL' AND DATE(t.executed_at) = ?
                         AND op.status != 'OPEN'
                       )""",
                    (ptype, yesterday)
                ).fetchall()
            total = len(rows)
            wins = sum(1 for r in rows if (r["pnl"] or 0) > 0)
            pnl_day = sum((r["pnl"] or 0) for r in rows)
            capital = float(database.get_setting(self._resolved_budget_key(), "0"))
            roi = self._compute_roi()
            notifications.notify_daily_summary(
                total_trades=total, wins=wins,
                pnl_day=pnl_day, capital=capital, roi_pct=roi,
            )
            # Snapshot équité pour graph historique (V14)
            try:
                from core import equity_history
                # Calcul unrealized P&L sur les positions ouvertes
                open_pos = database.get_open_positions(ptype)
                unrealized = sum(
                    (self._latest_prices.get(p["coin_id"], {}).get("price", p["entry_price"])
                     - p["entry_price"]) * p["quantity"]
                    for p in open_pos
                )
                mode = "paper" if paper_mode.is_paper_mode() else "real"
                equity_history.record_snapshot(
                    capital=capital,
                    unrealized_pnl=unrealized,
                    realized_pnl_today=pnl_day,
                    trades_today=total,
                    roi_pct=roi,
                    mode=mode,
                )
            except (ImportError, KeyError, ValueError) as exc:
                logger.warning(f"[BotMaitre] equity snapshot failed: {exc}")
        except (ImportError, KeyError, ValueError) as exc:
            logger.warning(f"[BotMaitre] daily summary failed: {exc}")

    def emergency_close_all_positions(self) -> int:
        """
        🚨 Ferme IMMÉDIATEMENT toutes les positions ouvertes du Bot Maître
        au prix marché actuel. Notifie chaque clôture via Telegram.

        Utilisé par :
          - Bouton "Emergency Stop" dans l'UI Settings
          - Commande Telegram /stop (futur)

        Retourne le nombre de positions fermées.
        """
        from core import market_data
        ptype = self._resolved_portfolio_type()
        positions = database.get_open_positions(ptype)
        if not positions:
            return 0

        # Récupérer les prix courants
        try:
            prices = market_data.get_prices()
        except (OSError, ValueError):
            prices = self._latest_prices or {}

        closed = 0
        for pos in positions:
            cid = pos["coin_id"]
            current_price = prices.get(cid, {}).get("price", pos["entry_price"])
            if current_price <= 0:
                current_price = pos["entry_price"]
            try:
                self._execute_exit(
                    pos, current_price, "EXIT_EMERGENCY",
                    f"Emergency stop @ {current_price:.4f}",
                )
                closed += 1
            except (exchange.BinanceError, KeyError, ValueError) as exc:
                logger.error(f"[BotMaitre] Emergency close {pos['symbol']} failed: {exc}")

        # Notification Telegram récap
        try:
            notifications.send_async(
                f"🚨 <b>EMERGENCY STOP</b>\n"
                f"Positions fermées : <b>{closed}/{len(positions)}</b>\n"
                f"Mode : {'PAPER' if paper_mode.is_paper_mode() else 'RÉEL'}"
            )
        except (ImportError, AttributeError):
            pass
        logger.warning(f"[BotMaitre] EMERGENCY STOP : {closed} positions fermees")
        return closed

    # ─── Cache OHLCV per-cycle (déduplique les HTTP calls) ──────────────────

    # Durée d'une bougie en secondes selon l'intervalle
    _INTERVAL_SECONDS = {
        "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
        "12h": 43200, "1d": 86400,
    }

    def _cached_ohlcv(self, coin_id: str, days: int, interval: str = "1h") -> list:
        """
        Fetch OHLCV avec cache per-cycle. Si une requête précédente dans le même
        cycle a demandé PLUS de jours sur le même coin+interval, on slice le
        résultat cached au lieu de refaire un appel HTTP.

        Gain typique : −40 à −60 % d'appels HTTP par cycle quand plusieurs
        candidats sont qualifiés.
        """
        from core.market_data import get_ohlcv_for_analysis

        key = (coin_id, interval)
        cached = self._cycle_ohlcv_cache.get(key)

        if cached is not None:
            cached_days, cached_candles = cached
            if cached_days >= days and cached_candles:
                # Cache hit : slicer le cache pour renvoyer la tranche demandée
                secs = self._INTERVAL_SECONDS.get(interval, 3600)
                needed = int(days * 86400 / secs) + 50   # +50 pour marge warmup
                if len(cached_candles) > needed:
                    return cached_candles[-needed:]
                return cached_candles

        # Cache miss (ou cached trop court) → fetch
        candles = get_ohlcv_for_analysis(coin_id, days=days, interval=interval)
        if candles:
            # Ne pas écraser un cache plus long avec un plus court
            if cached is None or cached[0] < days:
                self._cycle_ohlcv_cache[key] = (days, candles)
        return candles

    # ─── Fetch autonome des données marché ────────────────────────────────────

    def _fetch_own_data(self) -> tuple[dict, list]:
        try:
            from core.market_data import get_prices, get_historical_prices, DEFAULT_COINS
            from core import indicators as ind
            from core import signals as sig_module

            prices = get_prices()
            if not prices:
                return {}, []

            computed = []
            for coin in DEFAULT_COINS:
                cid    = coin["id"]
                symbol = coin["symbol"]
                candles = get_historical_prices(cid, days=30)
                if len(candles) < 30:
                    continue
                indics = ind.compute_all(candles)
                if not indics:
                    continue
                indics["current_price"] = prices.get(cid, {}).get("price", 0)
                ts = sig_module.analyze(cid, symbol, indics)
                computed.append(ts)

            logger.info(f"[BotMaitre] {len(computed)} signaux calculés en autonome")
            return prices, computed

        except Exception as exc:
            logger.error(f"[BotMaitre] Erreur fetch autonome: {exc}")
            return {}, []

    # ─── Trailing Stop-Loss ────────────────────────────────────────────────────

    def _update_trailing_stops(self, prices: dict, signals: list):
        """
        Remonte le SL des positions gagnantes pour verrouiller les profits.
        Utilise l'ATR actuel du signal s'il est dispo (s'adapte à la volatilité),
        sinon bascule sur un pourcentage fixe (fallback).
        """
        # Index coin_id → signal (pour retrouver l'ATR implicite via SL/prix)
        sig_index = {s.coin_id: s for s in signals}

        # Positions résolues selon paper_mode
        for pos in database.get_open_positions(self._resolved_portfolio_type()):
            cid   = pos["coin_id"]
            price = prices.get(cid, {}).get("price", 0)
            if price <= 0:
                continue

            entry    = pos["entry_price"]
            gain_pct = (price - entry) / entry * 100 if entry > 0 else 0

            if gain_pct < MASTER_CONFIG["trailing_activate_pct"]:
                continue

            # Estimer l'ATR depuis le signal courant si disponible
            # (price − stop_loss_suggéré) ≈ 1.5 × ATR → ATR ≈ (price − SL) / 1.5
            atr_est = None
            sig     = sig_index.get(cid)
            if sig and sig.stop_loss and sig.price > 0:
                spread = abs(sig.price - sig.stop_loss)
                if spread > 0:
                    atr_est = spread / 1.5

            if atr_est and atr_est > 0:
                new_sl = price - (MASTER_CONFIG["trailing_sl_atr_mult"] * atr_est)
            else:
                new_sl = price * (1 - MASTER_CONFIG["trailing_sl_fallback_pct"] / 100)

            new_sl = round(new_sl, 6)

            if new_sl > pos["stop_loss"]:
                database.update_position_sl(pos["id"], new_sl)
                logger.info(
                    f"[BotMaitre] Trailing SL {pos['symbol']}: "
                    f"{pos['stop_loss']:.4f} → {new_sl:.4f} | prix={price:.4f} | "
                    f"gain={gain_pct:+.2f}% | ATR_est={atr_est:.4f}"
                    if atr_est else
                    f"[BotMaitre] Trailing SL {pos['symbol']} (fallback %): "
                    f"{pos['stop_loss']:.4f} → {new_sl:.4f} | prix={price:.4f}"
                )

    # ─── Gestion des sorties Bot Maître ───────────────────────────────────────

    def _manage_master_exits(self, prices: dict, cycle_id: str = None) -> int:
        """
        Gère les sorties des positions ouvertes du Bot Maître.
        Ordre de priorité : SL > Partial TP1 > TP final.
        Retourne le nombre de positions entièrement fermées.
        """
        exits = 0
        use_partial = MASTER_CONFIG.get("use_partial_exits", False)
        partial_frac = MASTER_CONFIG.get("partial_exit_fraction", 0.5)

        # Positions résolues selon paper_mode (master vs master_paper)
        for pos in database.get_open_positions(self._resolved_portfolio_type()):
            price = prices.get(pos["coin_id"], {}).get("price", 0)
            if price <= 0:
                continue

            # Priorité 1 : Stop-Loss atteint → fermeture totale
            if price <= pos["stop_loss"]:
                self._execute_exit(
                    pos, price, "EXIT_SL",
                    f"Stop-Loss @ {price:.4f} ≤ SL:{pos['stop_loss']:.4f}",
                    cycle_id=cycle_id,
                )
                exits += 1
                continue

            # Priorité 2 : Partial TP1 atteint (si activé et pas encore pris)
            tp1 = pos.get("tp1_price")
            tp1_taken = pos.get("tp1_taken") or 0
            if (use_partial and tp1 and not tp1_taken
                and price >= tp1
                and price < pos["take_profit"]):
                # Vendre partial_frac de la position, remonter SL au break-even
                self._execute_partial_exit(
                    pos, price, fraction=partial_frac, cycle_id=cycle_id,
                )
                # Ne pas incrémenter exits (position encore ouverte)
                continue

            # Priorité 3 : Take-Profit final → fermeture totale du reste
            if price >= pos["take_profit"]:
                self._execute_exit(
                    pos, price, "EXIT_TP",
                    f"Take-Profit @ {price:.4f} ≥ TP:{pos['take_profit']:.4f}",
                    cycle_id=cycle_id,
                )
                exits += 1

        return exits

    def _execute_partial_exit(self, pos: dict, price: float,
                                fraction: float = 0.5,
                                cycle_id: str = None) -> None:
        """
        Exécute un Partial Exit :
          - Vend `fraction` de la quantité (50 % par défaut)
          - Remonte le SL au break-even (entry_price) sur la part restante
          - Flag tp1_taken = 1 pour éviter la répétition

        Philosophie : capture les profits à 1.5R, laisse courir le reste avec
        un risque nul (SL = break-even). Standard hedge fund.
        """
        cid = pos["coin_id"]
        sym = pos["symbol"]
        qty_total = pos["quantity"]
        qty_to_sell = qty_total * fraction
        qty_remaining = qty_total - qty_to_sell
        entry = pos["entry_price"]

        client = exchange.get_client()
        fee = qty_to_sell * price * 0.001

        try:
            actual_price = price
            ex_id = ""
            if client:
                order = client.place_market_order(f"{sym}USDT", "SELL", qty_to_sell)
                ex_id = str(order.get("order_id", ""))
                if order.get("fills"):
                    actual_price = float(order["fills"][0].get("price", price))
                get_circuit_breaker().report_api_success()

            # Enregistrer la vente partielle dans trades
            database.record_trade(
                cid, sym, "SELL", qty_to_sell, actual_price,
                fee=fee,
                source="AUTO_PARTIAL_MASTER",
                note=f"Partial {fraction*100:.0f}% @ {actual_price:.4f} "
                     f"(TP1, SL remonté au break-even)",
                exchange_id=ex_id,
            )

            # P&L de la part vendue
            pnl_partial = (actual_price - entry) * qty_to_sell - fee
            # On n'ajuste PAS budget_master ici : la vente réalise du cash qui
            # sera comptabilisé dans le calcul global de l'equity au prochain cycle.
            # Mais le P&L réalisé doit être ajouté au budget (cohérent avec _execute_exit).
            self._adjust_budget("master", pnl_partial)

            # Mise à jour de la position : qty réduite, SL = break-even
            database.update_position_after_partial_exit(
                position_id=pos["id"],
                new_quantity=qty_remaining,
                new_stop_loss=entry,   # break-even pour sécuriser le runner
            )

            database.log_auto_trader(
                "master", "PARTIAL_TP", cid, sym, actual_price, qty_to_sell,
                f"Partial {fraction*100:.0f}% @ {actual_price:.4f} | "
                f"P&L={pnl_partial:+.2f} | SL→break-even"
            )

            logger.info(
                f"[BotMaitre] PARTIAL_TP {sym} : vendu {qty_to_sell:.6f} "
                f"({fraction*100:.0f}%) @ {actual_price:.4f} | "
                f"P&L={pnl_partial:+.2f} | SL={entry:.4f} (break-even)"
            )

            # Audit + Notification Telegram
            audit.log_event(audit.AuditEvent(
                event_type="POSITION_CLOSED", coin_id=cid, symbol=sym,
                decision="PARTIAL_TP", severity="info",
                inputs={"entry_price": entry, "qty_total": qty_total,
                        "qty_sold": qty_to_sell, "fraction": fraction},
                outputs={"exit_price": actual_price, "pnl_usdt": pnl_partial,
                         "qty_remaining": qty_remaining, "new_sl": entry},
                reasoning=[f"TP1 partial exit @ {actual_price}, runner avec SL break-even"],
                cycle_id=cycle_id,
            ))

            # Notification partielle
            try:
                notifications.send_async(
                    f"💰 <b>PARTIAL TP</b> {sym}\n"
                    f"Vendu : {qty_to_sell:.6f} ({fraction*100:.0f}%)\n"
                    f"Prix : {actual_price:.4f}\n"
                    f"P&L partiel : <b>{pnl_partial:+.2f} USDT</b>\n"
                    f"Runner : {qty_remaining:.6f} restant, SL → break-even ({entry:.4f})"
                )
            except (ImportError, AttributeError):
                pass

        except (exchange.BinanceError, ValueError, KeyError) as exc:
            database.log_auto_trader("master", "ERROR", cid, sym, price, qty_to_sell, str(exc))
            logger.error(f"[BotMaitre] Erreur partial exit {sym}: {exc}")
            get_circuit_breaker().report_api_error(str(exc))

    # ─── Gestion des sorties anciens portefeuilles ────────────────────────────

    def _manage_exits(self, ptype: str, config: dict, prices: dict):
        for pos in database.get_open_positions(ptype):
            price = prices.get(pos["coin_id"], {}).get("price", 0)
            if price <= 0:
                continue
            if price <= pos["stop_loss"]:
                self._execute_exit(
                    pos, price, "EXIT_SL",
                    f"SL @ {price:.4f} ≤ {pos['stop_loss']:.4f}"
                )
            elif price >= pos["take_profit"]:
                self._execute_exit(
                    pos, price, "EXIT_TP",
                    f"TP @ {price:.4f} ≥ {pos['take_profit']:.4f}"
                )

    # ─── Exécution de la vente ────────────────────────────────────────────────

    def _execute_exit(self, pos: dict, price: float, action: str, reason: str,
                       cycle_id: str = None):
        ptype  = pos["portfolio_type"]
        cid    = pos["coin_id"]
        sym    = pos["symbol"]
        qty    = pos["quantity"]
        client = exchange.get_client()
        fee    = qty * price * 0.001

        try:
            actual_price = price
            ex_id        = ""

            if client:
                order = client.place_market_order(f"{sym}USDT", "SELL", qty)
                ex_id = str(order.get("order_id", ""))
                if order.get("fills"):
                    actual_price = float(order["fills"][0].get("price", price))
                get_circuit_breaker().report_api_success()

            database.record_trade(
                cid, sym, "SELL", qty, actual_price,
                fee=fee,
                source=f"AUTO_{action}_{ptype.upper()}",
                note=reason,
                exchange_id=ex_id,
            )
            database.close_open_position(pos["id"], action)

            pnl = (actual_price - pos["entry_price"]) * qty - fee
            self._adjust_budget(ptype, pnl)

            # Audit trail
            if ptype.startswith("master"):
                audit.log_position_closed(
                    coin_id=cid, symbol=sym,
                    entry_price=pos["entry_price"], exit_price=actual_price,
                    quantity=qty, pnl=pnl, reason=action, cycle_id=cycle_id,
                )
                # Report au circuit breaker
                hist = ps.compute_historical_stats(ptype)
                get_circuit_breaker().report_trade_result(
                    pnl=pnl, exit_reason=action, avg_loss=hist.get("avg_loss"),
                )

                # Notification Telegram de la clôture
                initial_risk_notif = (pos["entry_price"] - pos["stop_loss"]) * qty
                r_mult_notif = pnl / initial_risk_notif if initial_risk_notif > 0 else 0.0
                notifications.notify_exit(
                    coin_id=cid, symbol=sym,
                    entry_price=pos["entry_price"], exit_price=actual_price,
                    pnl=pnl, r_multiple=r_mult_notif, reason=action,
                )

                # Report à l'agent adaptatif via API publique unifiée
                # (record_trade_outcome encapsule : attribution par votes,
                # update tuner, persistence périodique, tout thread-safe).
                if MASTER_CONFIG.get("use_adaptive", False):
                    try:
                        import json as _json
                        agent = get_adaptive_agent()
                        initial_risk = (pos["entry_price"] - pos["stop_loss"]) * qty
                        r_multiple = pnl / initial_risk if initial_risk > 0 else 0.0

                        # Désérialiser les votes persistés à l'entrée
                        votes_json = pos.get("strategy_votes_json")
                        try:
                            votes = _json.loads(votes_json) if votes_json else {}
                        except (TypeError, ValueError):
                            votes = {}

                        credited = agent.record_trade_outcome(
                            regime=self._regime.value,
                            strategy_votes=votes,
                            profile_name=pos.get("profile_name") or "balanced",
                            win=(pnl > 0),
                            pnl=pnl,
                            r_multiple=r_multiple,
                        )
                        logger.info(
                            f"[Adaptive] Trade closed : {credited} strats creditees, "
                            f"profile={pos.get('profile_name') or 'balanced'}, "
                            f"win={pnl > 0}, R={r_multiple:+.2f}"
                        )
                    except (ImportError, KeyError, ValueError, ZeroDivisionError) as exc:
                        logger.warning(f"[BotMaitre] Adaptive update failed: {exc}")

            database.log_auto_trader(ptype, action, cid, sym, actual_price, qty, reason)
            logger.info(
                f"[BotMaitre] {action} {sym} ({ptype}) @ {actual_price:.4f} | "
                f"P&L: {pnl:+.2f} USDT"
            )

        except Exception as exc:
            database.log_auto_trader(ptype, "ERROR", cid, sym, price, qty, str(exc))
            logger.error(f"[BotMaitre] Erreur exit {sym}: {exc}")
            if ptype.startswith("master"):
                get_circuit_breaker().report_api_error(str(exc))

    # ─── Recherche d'entrées Bot Maître (version institutional intégrée) ─────

    def _look_for_master_entries_advanced(self, signals: list, prices: dict,
                                            budget: float, cycle_id: str = None) -> int:
        """
        Version INSTITUTIONAL : Kelly sizing + Correlation matrix + Ensemble vote.
        Retourne le nombre de nouvelles positions ouvertes.
        """
        # Portfolio type résolu selon paper_mode (master vs master_paper)
        ptype = self._resolved_portfolio_type()
        # IMPORTANT : relire le budget DEPUIS LA DB pour refléter les exits qui
        # viennent d'être exécutés dans ce même cycle (_adjust_budget aurait modifié
        # le budget de manière atomique). L'argument `budget` peut être stale.
        budget = float(database.get_setting(self._resolved_budget_key(), str(budget)))
        open_pos = database.get_open_positions(ptype)

        # Profil adaptatif : prendre en compte la TRANSITION si détectée
        # (permet de basculer progressivement vers le profil cible avant la bascule officielle)
        profile_regime = self._regime
        if (MASTER_CONFIG.get("use_regime_transition", True)
            and self._regime_transition.get("transitioning")
            and self._regime_transition.get("transition_score", 0) >= 0.5):
            try:
                target = Regime(self._regime_transition["to_regime"])
                # Blend : on adopte 50% le profil cible
                profile_current = get_profile(self._regime)
                profile_target  = get_profile(target)
                profile = {
                    k: (profile_current[k] + profile_target[k]) / 2
                    if isinstance(profile_current[k], (int, float))
                    else profile_current[k]
                    for k in profile_current
                }
                # max_positions doit rester entier
                profile["max_positions"] = int(round(profile["max_positions"]))
                logger.info(f"[BotMaitre] Profil transitoire actif "
                            f"({self._regime.value} -> {target.value})")
            except (ValueError, KeyError, TypeError) as exc:
                # Regime() invalide, clé manquante, ou type incorrect → fallback sur profil régime courant
                logger.warning(f"[BotMaitre] Blending transition failed: {exc}")
                profile = get_profile(self._regime)
        else:
            profile = get_profile(self._regime)

        # ── Agent Adaptatif : suggest_profile() pilote les paramètres ──
        # Écrase les valeurs statiques par les paramètres appris (ou recall memory)
        current_profile_name = "balanced"   # défaut
        if MASTER_CONFIG.get("use_adaptive", False):
            try:
                agent = get_adaptive_agent()
                suggestion = agent.suggest_profile(self._regime.value)
                suggested_params = suggestion.get("params", {})
                current_profile_name = suggestion.get("profile_name", "balanced")
                # Écraser SEULEMENT les paramètres gérés par le tuner
                for k in ("min_score", "min_confidence", "min_rr", "kelly_fraction"):
                    if k in suggested_params:
                        profile[k] = suggested_params[k]
                logger.info(
                    f"[BotMaitre] Profil adaptatif : {current_profile_name} "
                    f"(source={suggestion.get('source')}, conf={suggestion.get('confidence'):.2f})"
                )
                # Audit de la suggestion (traçabilité)
                audit.log_event(audit.AuditEvent(
                    event_type="CONFIG_CHANGED",
                    decision=current_profile_name,
                    severity="info",
                    inputs={"regime": self._regime.value, "source": suggestion.get("source")},
                    outputs={"profile": current_profile_name, "params": suggested_params},
                    reasoning=[suggestion.get("rationale", "")],
                    cycle_id=cycle_id,
                ))
            except (ImportError, KeyError, ValueError, TypeError) as exc:
                logger.warning(f"[BotMaitre] Adaptive suggest_profile failed: {exc}")

        # Override risk par user si défini (priorité FINALE sur l'adaptatif)
        user_risk = database.get_setting(MASTER_CONFIG["risk_key"], "")
        if user_risk:
            try:
                profile["risk_pct"] = float(user_risk)
            except ValueError:
                pass

        if len(open_pos) >= profile["max_positions"]:
            return 0

        invested = sum(p["entry_usdt"] for p in open_pos)
        max_invest = budget * profile["max_capital_pct"] / 100
        if invested >= max_invest:
            return 0

        already_holds = {p["coin_id"] for p in open_pos}

        # ─── Matrice de corrélation (si on a des positions ouvertes) ──────────
        correlation_matrix = {}
        if MASTER_CONFIG["use_correlation_block"] and already_holds:
            try:
                from core.market_data import DEFAULT_COINS
                # Fetch historique récent pour matrice (utilise le cache per-cycle
                # pour éviter les doublons avec MTF/ensemble/Kelly)
                coins_data = {}
                for c in DEFAULT_COINS:
                    candles = self._cached_ohlcv(c["id"], days=10, interval="1h")
                    if candles and len(candles) >= 50:
                        coins_data[c["id"]] = candles[-MASTER_CONFIG["correlation_lookback_candles"]:]
                if len(coins_data) >= 2:
                    correlation_matrix = corr.compute_correlation_matrix(coins_data)
            except Exception as exc:
                logger.warning(f"[BotMaitre] Correlation matrix failed: {exc}")

        # ─── Stats historiques pour Kelly ─────────────────────────────────────
        hist_stats = ps.compute_historical_stats(ptype, min_trades=10)

        # ─── Filtrage et qualification des candidats ──────────────────────────
        # Chaque candidat = (sig, strategy_votes_dict_or_None)
        # strategy_votes : {"trend_follower": True/False, ...} ← a-t-elle voté BUY ?
        candidates = []
        for sig in signals:
            # Filtre coin déjà détenu / cooldown
            if sig.coin_id in already_holds:
                continue
            if database.is_in_cooldown(ptype, sig.coin_id, MASTER_CONFIG["cooldown_hours"]):
                continue

            # Filtre de base (signal qualifié par seuils régime)
            if not self._qualifies_master(sig, profile):
                audit.log_signal_rejected(
                    sig.coin_id, sig.symbol, sig,
                    reason=f"Seuils regime {self._regime.value} non atteints",
                    threshold="profile_filter", cycle_id=cycle_id,
                )
                continue

            # Ensemble voting — capture aussi les votes individuels pour audit/adaptive
            strategy_votes: dict[str, bool] | None = None
            if MASTER_CONFIG["use_ensemble"]:
                try:
                    ens_decision = self._compute_ensemble_vote(sig)
                    if not ensemble.is_ensemble_qualified(
                        ens_decision,
                        min_agreement=MASTER_CONFIG["min_ensemble_agreement"],
                        min_score=MASTER_CONFIG["min_ensemble_score"],
                    ):
                        audit.log_signal_rejected(
                            sig.coin_id, sig.symbol, sig,
                            reason=f"Ensemble non qualifie : score={ens_decision.ensemble_score} "
                                   f"agreement={ens_decision.agreement_count}/3",
                            threshold="ensemble", cycle_id=cycle_id,
                        )
                        continue
                    # Attribution : True si la stratégie a voté BUY ou STRONG_BUY
                    strategy_votes = {
                        op.strategy: op.vote.value > 0
                        for op in ens_decision.opinions
                    }
                except (ImportError, KeyError, ValueError, TypeError) as exc:
                    logger.warning(f"[BotMaitre] Ensemble vote failed for {sig.coin_id}: {exc}")

            # Correlation block
            if MASTER_CONFIG["use_correlation_block"] and correlation_matrix and already_holds:
                too_corr, offender, corr_val = corr.is_too_correlated(
                    correlation_matrix, sig.coin_id, already_holds,
                    threshold=MASTER_CONFIG["correlation_threshold"],
                )
                if too_corr:
                    audit.log_correlation_block(
                        coin_id=sig.coin_id, correlated_with=offender or "unknown",
                        correlation=corr_val, cycle_id=cycle_id,
                    )
                    database.log_auto_trader(
                        ptype, "SKIP", sig.coin_id, sig.symbol,
                        sig.price, 0,
                        f"Correlation {corr_val:.2f} avec {offender} > seuil",
                    )
                    continue

            # ── MTF Confluence check (STANDARD PRO : trader avec la tendance long) ──
            # IMPORTANT : skip le filtre si < 3 TF disponibles (réseau dégradé,
            # coin récent, etc.). Aligné avec backtest pour cohérence — évite
            # une sur-stricture qui bloquerait tous les trades en cas d'un
            # seul fetch HTTP failed.
            if MASTER_CONFIG.get("use_mtf_confluence", True):
                try:
                    mtf_result = self._compute_mtf(sig.coin_id)
                    if mtf_result is not None and len(mtf_result.timeframes) >= 3:
                        if not mtf.is_confluence_valid_for_long(
                            mtf_result, min_confluence=MASTER_CONFIG["mtf_min_confluence"]
                        ):
                            audit.log_signal_rejected(
                                sig.coin_id, sig.symbol, sig,
                                reason=mtf.describe_confluence(mtf_result),
                                threshold="mtf_confluence", cycle_id=cycle_id,
                            )
                            database.log_auto_trader(
                                ptype, "SKIP", sig.coin_id, sig.symbol,
                                sig.price, 0,
                                f"MTF non aligne: {mtf_result.confluence_score}/"
                                f"{mtf_result.total_timeframes}",
                            )
                            continue
                    elif mtf_result is not None and len(mtf_result.timeframes) < 3:
                        # Soft pass : on log mais on laisse passer (données insuffisantes)
                        logger.info(
                            f"[BotMaitre] MTF skipped for {sig.coin_id}: "
                            f"only {len(mtf_result.timeframes)}/3 TF available"
                        )
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    logger.warning(f"[BotMaitre] MTF check failed for {sig.coin_id}: {exc}")

            audit.log_signal_qualified(sig.coin_id, sig.symbol, sig, cycle_id)

            # Candidat validé : on garde sig + votes individuels (pour attribution adaptive)
            candidates.append((sig, strategy_votes))

        # Trier par score descendant
        candidates.sort(key=lambda item: (item[0].score, item[0].risk_reward or 0), reverse=True)

        slots_left = profile["max_positions"] - len(open_pos)
        available  = min(budget - invested, max_invest - invested)
        entries_opened = 0

        for sig, strategy_votes in candidates[:slots_left]:
            # ── Kelly-based position sizing ──
            if MASTER_CONFIG["use_kelly_sizing"] and sig.price > sig.stop_loss:
                # ⚠ MODE COLD-START : si moins de 10 trades historiques,
                # les stats Kelly sont fictives. On limite drastiquement la
                # taille de position jusqu'à accumulation d'un échantillon réel.
                if hist_stats.get("is_defaults", False):
                    # Risque ultra-prudent : 1% du budget max, pas de Kelly
                    amount_usdt = min(budget * 0.01, 50.0)
                    sizing = {
                        "binding":  "cold_start",
                        "size_usdt": round(amount_usdt, 2),
                        "kelly_f":   0.0,
                        "note":      f"Cold start — {hist_stats['sample_size']}/10 trades",
                    }
                    logger.info(f"[BotMaitre] Cold start sizing pour {sig.symbol}: "
                                f"${amount_usdt:.2f} ({hist_stats['sample_size']}/10 trades reels)")
                else:
                    # Estimer la volatilité du coin depuis ses bougies récentes
                    # (cache per-cycle : dédupliqué avec MTF qui demande aussi 1h)
                    vol_pct = 2.0
                    try:
                        candles = self._cached_ohlcv(sig.coin_id, days=5, interval="1h")
                        if candles:
                            vol_pct = ps.realized_volatility_pct(candles)
                    except (ValueError, KeyError, TypeError, OSError) as exc:
                        logger.warning(f"[BotMaitre] Vol estimation failed {sig.coin_id}: {exc}")

                    # IMPORTANT : Kelly sizing RESPECTE les paramètres du profil régime.
                    # - max_risk_per_trade : vient du profil (bull=5%, neutral=3.5%, bear=2%)
                    # - max_position_pct   : vient du profil (bull=80%, neutral=60%, bear=40%)
                    # - kelly_fraction_used : 1/4 Kelly (constant MASTER_CONFIG)
                    sizing = ps.optimal_position_size(
                        capital               = budget,
                        win_rate              = hist_stats["win_rate"],
                        avg_win               = hist_stats["avg_win"],
                        avg_loss              = hist_stats["avg_loss"],
                        entry_price           = sig.price,
                        stop_loss             = sig.stop_loss,
                        realized_vol_pct      = vol_pct,
                        max_risk_per_trade    = profile["risk_pct"],
                        max_position_pct      = profile["max_capital_pct"],
                        kelly_fraction_used   = MASTER_CONFIG["kelly_fraction"],
                        vol_target_pct        = MASTER_CONFIG["vol_target_pct"],
                    )
                    amount_usdt = sizing["size_usdt"]

                audit.log_kelly_sizing(
                    coin_id=sig.coin_id,
                    win_rate=hist_stats["win_rate"],
                    avg_win=hist_stats["avg_win"],
                    avg_loss=hist_stats["avg_loss"],
                    kelly_f=sizing.get("kelly_f", 0),
                    fractional_kelly=sizing.get("kelly_f", 0),
                    final_size_usdt=amount_usdt,
                    cycle_id=cycle_id,
                )
            else:
                # Fallback : sizing simple par %
                amount_usdt = budget * profile["risk_pct"] / 100
                sizing = {"binding": "fixed_pct", "size_usdt": amount_usdt}

            if amount_usdt <= 0 or amount_usdt > available or available < 10.0:
                database.log_auto_trader(
                    ptype, "SKIP", sig.coin_id, sig.symbol,
                    sig.price, 0,
                    f"Sizing insuffisant ({sizing.get('binding','?')}: ${amount_usdt:.2f})"
                )
                continue

            self._execute_entry(
                ptype, sig, amount_usdt,
                sizing_info=sizing, cycle_id=cycle_id,
                strategy_votes=strategy_votes,
                profile_name=current_profile_name,
            )
            available -= amount_usdt
            entries_opened += 1
            already_holds.add(sig.coin_id)

        return entries_opened

    def _compute_ensemble_vote(self, sig) -> 'ensemble.EnsembleDecision':
        """
        Reconstruit le dict d'indicateurs nécessaire à l'ensemble voting
        à partir d'un TradeSignal existant.

        Si use_adaptive est activé, les weights des 3 stratégies proviennent
        du Thompson Sampling (adaptatif) au lieu des REGIME_WEIGHTS statiques.
        """
        from core import indicators as ind
        candles = self._cached_ohlcv(sig.coin_id, days=21, interval="1h")
        indics = ind.compute_all(candles) if candles and len(candles) >= 30 else {}
        indics["current_price"] = sig.price

        adaptive_weights = None
        if MASTER_CONFIG.get("use_adaptive", False):
            try:
                agent = get_adaptive_agent()
                adaptive_weights = agent.get_strategy_weights(self._regime.value)
            except (ImportError, KeyError, ValueError, TypeError) as exc:
                logger.warning(f"[BotMaitre] Adaptive weights failed, fallback static: {exc}")
                adaptive_weights = None

        return ensemble.vote(sig.coin_id, indics, regime=self._regime.value,
                             adaptive_weights=adaptive_weights)

    def _compute_mtf(self, coin_id: str) -> 'mtf.MTFConfluence':
        """
        Multi-Timeframe Confluence : analyse 1h + 4h + 1d simultanément.
        Utilise le cache per-cycle : MTF 1h se sert du cache rempli par
        ensemble (21j) ou Kelly (5j) s'il existe déjà.
        """
        candles_by_tf = {}
        for tf, days in (("1h", 5), ("4h", 30), ("1d", 180)):
            try:
                candles_by_tf[tf] = self._cached_ohlcv(coin_id, days=days, interval=tf)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning(f"[BotMaitre] MTF fetch {tf} {coin_id} failed: {exc}")
                candles_by_tf[tf] = []
        # Filtrer les timeframes sans données
        candles_by_tf = {k: v for k, v in candles_by_tf.items() if v and len(v) >= 30}
        return mtf.analyze_confluence(coin_id, candles_by_tf)

    def _qualifies_master(self, sig, profile: dict) -> bool:
        """
        Filtre paramétré par le profil adapté au régime de marché courant.
        Le check STRONG_BUY est explicite pour forcer l'intention haussière
        (même si min_score baissait un jour, on resterait protégé).
        """
        if sig.signal is not Signal.STRONG_BUY:
            return False
        if sig.score < profile["min_score"]:
            return False
        if sig.confidence < profile["min_confidence"]:
            return False
        if sig.risk_reward is None or sig.risk_reward < profile["min_rr"]:
            return False
        return True

    # ─── Recherche d'entrées anciens portefeuilles ────────────────────────────

    def _look_for_entries(
        self, ptype: str, config: dict, signals: list, prices: dict, budget: float
    ):
        open_pos   = database.get_open_positions(ptype)
        open_count = len(open_pos)
        if open_count >= config["max_positions"]:
            return

        slots_left    = config["max_positions"] - open_count
        already_holds = {p["coin_id"] for p in open_pos}

        candidates = [
            sig for sig in signals
            if self._qualifies_legacy(sig, config)
            and sig.coin_id not in already_holds
            and not database.is_in_cooldown(ptype, sig.coin_id, config["cooldown_hours"])
        ]
        candidates.sort(key=lambda s: (s.score, s.risk_reward or 0), reverse=True)

        used_budget = sum(p["entry_usdt"] for p in open_pos)
        available   = budget - used_budget

        for sig in candidates[:slots_left]:
            amount_usdt = budget * config["risk_pct"] / 100
            if amount_usdt > available or available < 5.0:
                database.log_auto_trader(
                    ptype, "SKIP", sig.coin_id, sig.symbol,
                    sig.price, 0, "Budget disponible insuffisant"
                )
                continue
            self._execute_entry(ptype, sig, amount_usdt)
            available -= amount_usdt

    def _qualifies_legacy(self, sig, config: dict) -> bool:
        # Legacy portfolios demandent min_score ≥ 50, donc seul STRONG_BUY peut
        # passer. On garde un check explicite de signal pour la lisibilité
        # (protection si min_score baisse un jour dans la config).
        if sig.signal is not Signal.STRONG_BUY:
            return False
        if sig.score < config["min_score"]:
            return False
        if sig.confidence < config["min_confidence"]:
            return False
        if sig.risk_reward is None or sig.risk_reward < config["min_rr"]:
            return False
        allowed = config.get("allowed_coins")
        if allowed and sig.coin_id not in allowed:
            return False
        return True

    # ─── Exécution de l'achat ─────────────────────────────────────────────────

    def _execute_entry(self, ptype: str, sig, amount_usdt: float,
                        sizing_info: Optional[dict] = None,
                        cycle_id: Optional[str] = None,
                        strategy_votes: Optional[dict] = None,
                        profile_name: Optional[str] = None):
        client = exchange.get_client()
        price  = sig.price
        fee    = amount_usdt * 0.001
        qty    = (amount_usdt - fee) / price if price > 0 else 0

        if qty <= 0:
            return

        if ptype.startswith("master"):
            cfg_name = MASTER_CONFIG["name"] + (" [PAPER]" if ptype == "master_paper" else "")
        else:
            cfg_name = LEGACY_PORTFOLIOS.get(ptype, {}).get("name", ptype)

        try:
            actual_price = price
            actual_qty   = qty
            ex_id        = ""

            if client:
                order        = client.place_market_order_usdt(f"{sig.symbol}USDT", "BUY", amount_usdt)
                ex_id        = str(order.get("order_id", ""))
                actual_qty   = float(order.get("executed_qty", qty))
                if order.get("fills"):
                    actual_price = float(order["fills"][0].get("price", price))

            note = (
                f"AUTO {cfg_name} | "
                f"Score:{sig.score:.0f} Conf:{sig.confidence:.0f}% "
                f"R/R:{sig.risk_reward} SL:{sig.stop_loss:.4f} TP:{sig.take_profit:.4f}"
            )

            database.record_trade(
                sig.coin_id, sig.symbol, "BUY", actual_qty, actual_price,
                fee=fee,
                source=f"AUTO_ENTRY_{ptype.upper()}",
                note=note,
                exchange_id=ex_id,
            )
            database.open_auto_position(
                ptype, sig.coin_id, sig.symbol,
                actual_price, actual_qty,
                sig.stop_loss, sig.take_profit, amount_usdt,
                strategy_votes=strategy_votes,    # pour l'attribution adaptive
                profile_name=profile_name,        # pour le ParameterTuner
            )
            database.log_auto_trader(
                ptype, "ENTRY", sig.coin_id, sig.symbol,
                actual_price, actual_qty, note
            )
            logger.info(f"[BotMaitre] ENTRY {sig.symbol} ({ptype}) @ {actual_price:.4f}")

            # Audit trail institutional + Notification Telegram
            if ptype.startswith("master"):
                notifications.notify_entry(
                    coin_id=sig.coin_id, symbol=sig.symbol,
                    entry_price=actual_price, quantity=actual_qty,
                    amount_usdt=amount_usdt,
                    sl=sig.stop_loss, tp=sig.take_profit,
                    regime=self._regime.value,
                    profile=profile_name,
                )
                audit.log_entry_executed(
                    coin_id=sig.coin_id, symbol=sig.symbol,
                    price=actual_price, quantity=actual_qty,
                    amount_usdt=amount_usdt,
                    sl=sig.stop_loss, tp=sig.take_profit,
                    sizing_info=sizing_info or {},
                    cycle_id=cycle_id,
                )

        except Exception as exc:
            database.log_auto_trader(ptype, "ERROR", sig.coin_id, sig.symbol, price, 0, str(exc))
            logger.error(f"[BotMaitre] Erreur entry {sig.symbol}: {exc}")
            if ptype.startswith("master"):
                get_circuit_breaker().report_api_error(str(exc))

    # ─── Utilitaires ──────────────────────────────────────────────────────────

    def _check_drawdown(self, current_budget: float) -> bool:
        # Capital initial résolu selon paper_mode
        initial = float(database.get_setting(self._resolved_initial_key(), "0"))
        if initial <= 0:
            return False
        drawdown_pct = (initial - current_budget) / initial * 100
        return drawdown_pct >= MASTER_CONFIG["max_drawdown_pct"]

    def _compute_roi(self) -> float:
        # ROI résolu selon paper_mode (séparé du réel)
        initial = float(database.get_setting(self._resolved_initial_key(), "0"))
        current = float(database.get_setting(self._resolved_budget_key(), "0"))
        if initial <= 0:
            return 0.0
        return (current - initial) / initial * 100

    def _adjust_budget(self, ptype: str, pnl: float):
        """Ajoute atomiquement le P&L réalisé au budget du portefeuille (thread-safe SQL)."""
        # Pour master/master_paper : utiliser le budget résolu
        if ptype in ("master", "master_paper"):
            key = self._resolved_budget_key()
        else:
            key = LEGACY_PORTFOLIOS.get(ptype, {}).get("budget_key", f"budget_{ptype}")
        database.increment_numeric_setting(key, pnl, default=0.0)


# ─── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[AutoTrader] = None


def get_auto_trader() -> AutoTrader:
    global _instance
    if _instance is None:
        _instance = AutoTrader()
    return _instance
