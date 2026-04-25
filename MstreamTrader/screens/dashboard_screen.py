"""
MstreamTrader - Écran Dashboard Principal
Affiche : prix en temps réel, top opportunités, solde, stats
"""

from kivy.uix.screenmanager import Screen
from kivy.clock import Clock
from kivy.properties import StringProperty, ListProperty, NumericProperty

from core import market_data, indicators, signals, database


class DashboardScreen(Screen):
    usdt_balance     = StringProperty("Non configuré")
    portfolio_value  = StringProperty("$0.00")
    total_pnl_text   = StringProperty("")
    pnl_color        = ListProperty([1, 1, 1, 1])
    last_update      = StringProperty("En attente...")
    status_text      = StringProperty("Connexion aux marchés...")
    win_rate_text    = StringProperty("0%")
    top_signal_text  = StringProperty("Analyse en cours...")
    top_signal_color = ListProperty([0.9, 0.75, 0.1, 1])
    api_configured   = StringProperty("Non configuré")
    api_status_color = ListProperty([0.6, 0.5, 0.1, 1])
    prices_source    = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._prices        = {}
        self._signals       = []
        self._refresh_event = None
        self._fetching      = False   # anti-spam threads
        self._fetch_lock    = None    # Lock créé à la demande

    def on_enter(self):
        database.init_db()
        self._refresh_event = Clock.schedule_interval(self._refresh, 30)
        self._refresh(0)

    def on_leave(self):
        if self._refresh_event:
            self._refresh_event.cancel()

    def _refresh(self, dt):
        """Lance un fetch en background si aucun n'est en cours."""
        from threading import Thread, Lock
        if self._fetch_lock is None:
            self._fetch_lock = Lock()

        # Test non bloquant — skip si un fetch est déjà en cours
        if not self._fetch_lock.acquire(blocking=False):
            return
        Thread(target=self._fetch_data_safe, daemon=True).start()

    def _fetch_data_safe(self):
        """Wrapper qui libère le lock même en cas d'exception."""
        try:
            self._fetch_data()
        finally:
            if self._fetch_lock is not None:
                try:
                    self._fetch_lock.release()
                except RuntimeError:
                    pass

    def _fetch_data(self):
        self.status_text = "Actualisation..."
        prices = market_data.get_prices()
        if not prices:
            err = market_data.last_fetch_error or "réseau indisponible"
            # Tronquer pour rester lisible dans la status bar
            if len(err) > 80:
                err = err[:77] + "..."
            self.status_text = f"Hors ligne : {err}"
            return

        self._prices = prices

        # Générer les signaux pour chaque coin
        new_signals = []
        for coin_def in market_data.DEFAULT_COINS:
            cid    = coin_def["id"]
            symbol = coin_def["symbol"]
            candles = market_data.get_historical_prices(cid, days=30)
            if len(candles) >= 30:
                indics = indicators.compute_all(candles)
                if indics:
                    if cid in prices:
                        indics["current_price"] = prices[cid]["price"]
                    sig = signals.analyze(cid, symbol, indics)
                    new_signals.append(sig)
                    database.log_signal(sig)

        self._signals = signals.rank_opportunities(new_signals)

        # Alertes prix
        triggered = database.check_alerts(prices)
        for alert in triggered:
            self._show_alert_notification(alert)

        Clock.schedule_once(lambda dt: self._update_ui(), 0)

    def _update_ui(self):
        from core.market_data import format_price, format_large_number

        # Solde USDT — réel uniquement si Binance configuré ou saisi manuellement
        balance = float(database.get_setting("usdt_balance", "0"))
        api_key = database.get_setting_encrypted("binance_api_key", "")
        if balance == 0.0 and not api_key:
            self.usdt_balance = "Configurer Binance"
        elif balance == 0.0:
            self.usdt_balance = "$0.00 (synchro...)"
        else:
            self.usdt_balance = f"${balance:,.2f}"

        # Indicateur source des données
        if api_key:
            self.api_configured   = "Binance OK - Données de votre compte réel"
            self.api_status_color = [0.0, 0.85, 0.4, 1]
        else:
            self.api_configured   = "CoinGecko API — Prix marché en direct (sans compte)"
            self.api_status_color = [0.5, 0.75, 1.0, 1]
        self.prices_source = f"{len(self._prices)} cryptos en direct"

        # Valeur portefeuille
        pv = database.calculate_portfolio_value(self._prices)
        self.portfolio_value = f"${pv['total_value']:,.2f}"
        pnl = pv["total_pnl"]
        self.total_pnl_text = f"{'+'if pnl>=0 else ''}{pnl:,.2f} USDT ({pv['total_pnl_pct']:+.1f}%)"
        self.pnl_color = [0.0, 0.85, 0.4, 1] if pnl >= 0 else [0.9, 0.2, 0.2, 1]

        # Stats trades
        stats = database.get_trade_stats()
        self.win_rate_text = f"{stats['win_rate']}%"

        # Meilleur signal
        buys = [s for s in self._signals
                if s.signal.value in ("BUY", "STRONG_BUY")]
        if buys:
            best = buys[0]
            self.top_signal_text  = f"{best.symbol} {best.signal_label} ({best.confidence:.0f}%)"
            self.top_signal_color = list(best.color)
        else:
            self.top_signal_text  = "Aucune opportunité forte"
            self.top_signal_color = [0.9, 0.75, 0.1, 1]

        from datetime import datetime
        self.last_update = datetime.now().strftime("%H:%M:%S")
        self.status_text = f"{len(self._signals)} actifs analysés"

        # Mettre à jour la liste des prix
        if hasattr(self.ids, "coin_list"):
            self.ids.coin_list.refresh(self._prices, self._signals)

    def _show_alert_notification(self, alert: dict):
        pass  # Géré par la notification Android/système

    def get_signals(self):
        return self._signals

    def get_prices(self):
        return self._prices

    def force_refresh(self):
        self._refresh(0)
