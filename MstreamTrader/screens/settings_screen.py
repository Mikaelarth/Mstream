"""
MstreamTrader - Écran Paramètres
Configuration des clés API Binance, risque, alertes
"""

from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.switch import Switch
from kivy.properties import StringProperty, BooleanProperty, ListProperty
from kivy.metrics import dp
from kivy.clock import Clock

from core import database, exchange
from core import notifications, paper_mode, validation


class SettingsScreen(Screen):
    status_text      = StringProperty("")
    status_color     = ListProperty([1, 1, 1, 1])
    auto_trade       = BooleanProperty(False)
    risk_per_trade   = StringProperty("2.0")
    master_active    = BooleanProperty(False)
    master_roi_text  = StringProperty("ROI: +0.00%")
    master_roi_color = ListProperty([0.0, 0.85, 0.4, 1])
    securite_active  = BooleanProperty(False)
    libre_active     = BooleanProperty(False)
    # Telegram + Paper mode (V12)
    telegram_status  = StringProperty("Non configuré")
    telegram_color   = ListProperty([0.6, 0.6, 0.6, 1])
    paper_active     = BooleanProperty(False)
    paper_roi_text   = StringProperty("Paper mode inactif")

    def on_enter(self):
        self._load_settings()

    def _load_settings(self):
        if hasattr(self.ids, "api_key_input"):
            key = database.get_setting_encrypted("binance_api_key")
            self.ids.api_key_input.text = key if key else ""

        if hasattr(self.ids, "api_secret_input"):
            secret = database.get_setting_encrypted("binance_api_secret")
            self.ids.api_secret_input.text = secret if secret else ""

        if hasattr(self.ids, "risk_input"):
            self.ids.risk_input.text = database.get_setting("risk_per_trade", "2.0")

        if hasattr(self.ids, "balance_input"):
            self.ids.balance_input.text = database.get_setting("usdt_balance", "0.0")

        auto = database.get_setting("auto_trade", "false") == "true"
        self.auto_trade = auto
        if hasattr(self.ids, "auto_switch"):
            self.ids.auto_switch.active = auto

        # ── Bot Maître ─────────────────────────────────────────────────────────
        if hasattr(self.ids, "budget_master_input"):
            self.ids.budget_master_input.text = database.get_setting("budget_master", "0.0")
        if hasattr(self.ids, "risk_master_input"):
            self.ids.risk_master_input.text = database.get_setting("risk_master", "5.0")
        master_on = database.get_setting("auto_trade_master", "false") == "true"
        self.master_active = master_on
        if hasattr(self.ids, "master_switch"):
            self.ids.master_switch.active = master_on
        self._refresh_master_roi()

        # ── Portefeuille Sécurité (legacy) ─────────────────────────────────────
        if hasattr(self.ids, "budget_securite_input"):
            self.ids.budget_securite_input.text = database.get_setting("budget_securite", "0.0")
        sec_on = database.get_setting("auto_trade_securite", "false") == "true"
        self.securite_active = sec_on
        if hasattr(self.ids, "securite_switch"):
            self.ids.securite_switch.active = sec_on

        # ── Portefeuille Libre (legacy) ────────────────────────────────────────
        if hasattr(self.ids, "budget_libre_input"):
            self.ids.budget_libre_input.text = database.get_setting("budget_libre", "0.0")
        if hasattr(self.ids, "risk_libre_input"):
            self.ids.risk_libre_input.text = database.get_setting("risk_libre", "3.0")
        lib_on = database.get_setting("auto_trade_libre", "false") == "true"
        self.libre_active = lib_on
        if hasattr(self.ids, "libre_switch"):
            self.ids.libre_switch.active = lib_on

        # ── Telegram (V12) ─────────────────────────────────────────────────────
        if hasattr(self.ids, "telegram_token_input"):
            self.ids.telegram_token_input.text = database.get_setting_encrypted("telegram_bot_token")
        if hasattr(self.ids, "telegram_chat_input"):
            self.ids.telegram_chat_input.text = database.get_setting_encrypted("telegram_chat_id")
        self._refresh_telegram_status()

        # ── Paper Mode (V12) ───────────────────────────────────────────────────
        if hasattr(self.ids, "paper_budget_input"):
            self.ids.paper_budget_input.text = database.get_setting("budget_master_paper", "0.0")
        paper_on = paper_mode.is_paper_mode()
        self.paper_active = paper_on
        if hasattr(self.ids, "paper_switch"):
            self.ids.paper_switch.active = paper_on
        self._refresh_paper_roi()

    def _refresh_telegram_status(self):
        if notifications.is_configured():
            self.telegram_status = "Configuré"
            self.telegram_color  = [0.0, 0.85, 0.4, 1]
        else:
            self.telegram_status = "Non configuré"
            self.telegram_color  = [0.6, 0.6, 0.6, 1]

    def _refresh_paper_roi(self):
        stats = paper_mode.get_paper_stats()
        if stats["budget_initial"] > 0:
            self.paper_roi_text = (
                f"Capital: ${stats['budget_current']:,.2f} | "
                f"ROI: {stats['roi_pct']:+.2f}% | "
                f"Trades: {stats['trades_count']}"
            )
        else:
            self.paper_roi_text = (
                "Paper mode inactif" if not stats["active"]
                else "Paper actif — définissez un budget initial"
            )

    def _refresh_master_roi(self):
        initial = float(database.get_setting("budget_master_initial", "0"))
        current = float(database.get_setting("budget_master", "0"))
        if initial > 0:
            roi = (current - initial) / initial * 100
            self.master_roi_text  = f"ROI: {roi:+.2f}%  |  Capital: ${current:,.2f}"
            self.master_roi_color = [0.0, 0.85, 0.4, 1] if roi >= 0 else [0.9, 0.2, 0.2, 1]
        else:
            self.master_roi_text  = "Budget non encore configuré"
            self.master_roi_color = [0.5, 0.5, 0.5, 1]

    # ─── Bot Maître ───────────────────────────────────────────────────────────

    def save_budget_master(self):
        if not hasattr(self.ids, "budget_master_input"):
            return
        try:
            budget = float(self.ids.budget_master_input.text)
            if budget <= 0:
                self._show_status("Le budget doit être > 0 USDT", error=True)
                return
            database.set_setting("budget_master", str(budget))
            # Mémoriser le capital initial uniquement à la première configuration
            initial = float(database.get_setting("budget_master_initial", "0"))
            if initial <= 0:
                database.set_setting("budget_master_initial", str(budget))
            self._refresh_master_roi()
            self._show_status(f"Budget Bot Maître: ${budget:,.2f} USDT sauvegardé")
        except ValueError:
            self._show_status("Valeur invalide", error=True)

    def reset_master_initial(self):
        """Réinitialise le capital initial (point de référence du ROI)."""
        current = float(database.get_setting("budget_master", "0"))
        if current > 0:
            database.set_setting("budget_master_initial", str(current))
            self._refresh_master_roi()
            self._show_status(f"Capital initial réinitialisé à ${current:,.2f}")

    def save_risk_master(self):
        if not hasattr(self.ids, "risk_master_input"):
            return
        try:
            risk = float(self.ids.risk_master_input.text)
            if 1.0 <= risk <= 20.0:
                database.set_setting("risk_master", str(risk))
                self._show_status(f"Risque Bot Maître: {risk}% par trade")
            else:
                self._show_status("Risque entre 1% et 20%", error=True)
        except ValueError:
            self._show_status("Valeur invalide", error=True)

    def toggle_master(self, value: bool):
        self.master_active = value
        budget = float(database.get_setting("budget_master", "0"))
        if value:
            if budget <= 0:
                self._show_status("Définissez d'abord un budget > 0 !", error=True)
                self.master_active = False
                database.set_setting("auto_trade_master", "false")
                if hasattr(self.ids, "master_switch"):
                    Clock.schedule_once(
                        lambda dt: setattr(self.ids.master_switch, "active", False), 0
                    )
            else:
                database.set_setting("auto_trade_master", "true")
                self._show_status(
                    f"BOT MAÎTRE ACTIVÉ — Capital: ${budget:,.2f} USDT | "
                    f"Cycles toutes les 5 min"
                )
        else:
            database.set_setting("auto_trade_master", "false")
            self._show_status("Bot Maître DÉSACTIVÉ")

    # ─── Telegram (V12) ────────────────────────────────────────────────────────

    def save_telegram_credentials(self):
        if not (hasattr(self.ids, "telegram_token_input") and hasattr(self.ids, "telegram_chat_input")):
            return
        token = self.ids.telegram_token_input.text.strip()
        chat_id = self.ids.telegram_chat_input.text.strip()

        # Validation avant sauvegarde
        ok_t, msg_t = validation.validate_setting("telegram_bot_token", token) if token else (True, "")
        ok_c, msg_c = validation.validate_setting("telegram_chat_id", chat_id) if chat_id else (True, "")
        if not ok_t:
            self._show_status(msg_t, error=True); return
        if not ok_c:
            self._show_status(msg_c, error=True); return

        notifications.set_credentials(token, chat_id)
        self._refresh_telegram_status()
        self._show_status("Credentials Telegram chiffrés & sauvegardés")

    def test_telegram_connection(self):
        from threading import Thread
        Thread(target=self._do_telegram_test, daemon=True).start()

    def _do_telegram_test(self):
        ok, msg = notifications.test_connection()
        Clock.schedule_once(lambda dt: self._show_status(msg, error=not ok), 0)

    def clear_telegram_credentials(self):
        notifications.clear_credentials()
        if hasattr(self.ids, "telegram_token_input"):
            self.ids.telegram_token_input.text = ""
        if hasattr(self.ids, "telegram_chat_input"):
            self.ids.telegram_chat_input.text = ""
        self._refresh_telegram_status()
        self._show_status("Credentials Telegram effacés")

    # ─── Paper Trading mode (V12) ──────────────────────────────────────────────

    def save_paper_budget(self):
        if not hasattr(self.ids, "paper_budget_input"):
            return
        try:
            budget = float(self.ids.paper_budget_input.text)
        except ValueError:
            self._show_status("Budget paper invalide", error=True); return
        if budget < 0:
            self._show_status("Budget paper doit être >= 0", error=True); return
        paper_mode.init_paper_budget(budget)
        self._refresh_paper_roi()
        self._show_status(f"Budget paper initialisé : ${budget:,.2f}")

    def toggle_paper_mode(self, active: bool):
        paper_mode.set_paper_mode(active)
        self.paper_active = active
        self._refresh_paper_roi()
        if active:
            self._show_status("PAPER MODE ACTIVÉ — ledger séparé, zero risque réel")
        else:
            self._show_status("Paper mode désactivé — retour au mode réel")

    # ─── Emergency Stop (D5) ───────────────────────────────────────────────────

    def emergency_stop_all(self):
        """
        🚨 Arrêt d'urgence : ferme TOUTES les positions ouvertes du Bot Maître
        au prix marché actuel. Utilisable depuis l'UI ou via Telegram /stop.
        """
        from threading import Thread
        # Confirmation par double-tap : on demande au user de re-cliquer
        if not getattr(self, "_emergency_stop_confirmed", False):
            self._emergency_stop_confirmed = True
            self._show_status("ATTENTION : Cliquer à nouveau pour CONFIRMER l'arret d'urgence", error=True)
            Clock.schedule_once(lambda dt: setattr(self, "_emergency_stop_confirmed", False), 5)
            return
        self._emergency_stop_confirmed = False
        Thread(target=self._do_emergency_stop, daemon=True).start()

    def _do_emergency_stop(self):
        try:
            from core.auto_trader import get_auto_trader
            bot = get_auto_trader()
            closed = bot.emergency_close_all_positions()
            Clock.schedule_once(
                lambda dt: self._show_status(
                    f"🚨 Emergency stop : {closed} positions fermées", error=False), 0
            )
        except (ImportError, AttributeError, Exception) as exc:
            Clock.schedule_once(
                lambda dt: self._show_status(f"Echec emergency stop : {exc}", error=True), 0
            )

    def save_api_keys(self):
        """Sauvegarde les clés API Binance."""
        if not hasattr(self.ids, "api_key_input"):
            return

        api_key    = self.ids.api_key_input.text.strip()
        api_secret = self.ids.api_secret_input.text.strip()

        if not api_key or not api_secret:
            self._show_status("Veuillez remplir les deux champs", error=True)
            return

        database.set_setting_encrypted("binance_api_key",    api_key)
        database.set_setting_encrypted("binance_api_secret", api_secret)
        exchange.invalidate_client_cache()   # forcer recréation avec les nouvelles clés
        self._show_status("Clés chiffrées & sauvegardées. Test de connexion…")

        from threading import Thread
        Thread(target=self._test_binance, daemon=True).start()

    def _test_binance(self):
        client = exchange.get_client()
        if client and client.test_connection():
            try:
                balance = client.get_usdt_balance()
                database.set_setting("usdt_balance", str(balance))
                Clock.schedule_once(lambda dt: self._show_status(
                    f"Connexion Binance réussie! Solde USDT: ${balance:,.2f}", error=False
                ), 0)
            except exchange.BinanceError as e:
                Clock.schedule_once(lambda dt: self._show_status(str(e), error=True), 0)
        else:
            Clock.schedule_once(lambda dt: self._show_status(
                "Connexion échouée — Vérifiez vos clés API", error=True
            ), 0)

    def save_risk_settings(self):
        if hasattr(self.ids, "risk_input"):
            try:
                risk = float(self.ids.risk_input.text)
                if 0.1 <= risk <= 10:
                    database.set_setting("risk_per_trade", str(risk))
                    self._show_status(f"Risque par trade: {risk}% sauvegardé")
                else:
                    self._show_status("Risque entre 0.1% et 10%", error=True)
            except ValueError:
                self._show_status("Valeur invalide", error=True)

    def save_balance(self):
        if hasattr(self.ids, "balance_input"):
            try:
                balance = float(self.ids.balance_input.text)
                if balance >= 0:
                    database.set_setting("usdt_balance", str(balance))
                    self._show_status(f"Solde USDT mis à jour: ${balance:,.2f}")
                else:
                    self._show_status("Solde invalide", error=True)
            except ValueError:
                self._show_status("Valeur invalide", error=True)

    def toggle_auto_trade(self, value: bool):
        self.auto_trade = value
        database.set_setting("auto_trade", "true" if value else "false")
        if value:
            self._show_status(
                "Trading automatique ACTIVÉ — Les signaux forts seront exécutés"
            )
        else:
            self._show_status("Trading automatique DÉSACTIVÉ")

    # ─── Portefeuille Sécurité ────────────────────────────────────────────────

    def save_budget_securite(self):
        if not hasattr(self.ids, "budget_securite_input"):
            return
        try:
            budget = float(self.ids.budget_securite_input.text)
            if budget >= 0:
                database.set_setting("budget_securite", str(budget))
                self._show_status(f"Budget Sécurité: ${budget:,.2f} USDT sauvegardé")
            else:
                self._show_status("Budget invalide", error=True)
        except ValueError:
            self._show_status("Valeur invalide", error=True)

    def toggle_securite(self, value: bool):
        self.securite_active = value
        database.set_setting("auto_trade_securite", "true" if value else "false")
        budget = float(database.get_setting("budget_securite", "0"))
        if value:
            if budget <= 0:
                self._show_status(
                    "Définissez d'abord un budget Sécurité > 0 !", error=True
                )
                self.securite_active = False
                database.set_setting("auto_trade_securite", "false")
                if hasattr(self.ids, "securite_switch"):
                    Clock.schedule_once(
                        lambda dt: setattr(self.ids.securite_switch, "active", False), 0
                    )
            else:
                self._show_status(
                    f"Portefeuille SÉCURITÉ activé — Budget: ${budget:,.2f} USDT"
                )
        else:
            self._show_status("Portefeuille Sécurité DÉSACTIVÉ")

    # ─── Portefeuille Libre ───────────────────────────────────────────────────

    def save_budget_libre(self):
        if not hasattr(self.ids, "budget_libre_input"):
            return
        try:
            budget = float(self.ids.budget_libre_input.text)
            if budget >= 0:
                database.set_setting("budget_libre", str(budget))
                self._show_status(f"Budget Libre: ${budget:,.2f} USDT sauvegardé")
            else:
                self._show_status("Budget invalide", error=True)
        except ValueError:
            self._show_status("Valeur invalide", error=True)

    def save_risk_libre(self):
        if not hasattr(self.ids, "risk_libre_input"):
            return
        try:
            risk = float(self.ids.risk_libre_input.text)
            if 0.5 <= risk <= 10:
                database.set_setting("risk_libre", str(risk))
                self._show_status(f"Risque Libre: {risk}% par trade sauvegardé")
            else:
                self._show_status("Risque entre 0.5% et 10%", error=True)
        except ValueError:
            self._show_status("Valeur invalide", error=True)

    def toggle_libre(self, value: bool):
        self.libre_active = value
        database.set_setting("auto_trade_libre", "true" if value else "false")
        budget = float(database.get_setting("budget_libre", "0"))
        if value:
            if budget <= 0:
                self._show_status(
                    "Définissez d'abord un budget Libre > 0 !", error=True
                )
                self.libre_active = False
                database.set_setting("auto_trade_libre", "false")
                if hasattr(self.ids, "libre_switch"):
                    Clock.schedule_once(
                        lambda dt: setattr(self.ids.libre_switch, "active", False), 0
                    )
            else:
                self._show_status(
                    f"Portefeuille LIBRE activé — Budget: ${budget:,.2f} USDT"
                )
        else:
            self._show_status("Portefeuille Libre DÉSACTIVÉ")

    def sync_binance_balance(self):
        """Synchronise le solde réel depuis Binance."""
        self._show_status("Synchronisation…")
        from threading import Thread
        Thread(target=self._sync_balance, daemon=True).start()

    def _sync_balance(self):
        client = exchange.get_client()
        if not client:
            Clock.schedule_once(lambda dt: self._show_status(
                "Configurez d'abord vos clés API", error=True
            ), 0)
            return
        try:
            balance = client.get_usdt_balance()
            database.set_setting("usdt_balance", str(balance))
            if hasattr(self.ids, "balance_input"):
                Clock.schedule_once(lambda dt: setattr(
                    self.ids.balance_input, "text", f"{balance:.2f}"
                ), 0)
            Clock.schedule_once(lambda dt: self._show_status(
                f"Solde synchronisé: ${balance:,.2f} USDT"
            ), 0)
        except exchange.BinanceError as e:
            Clock.schedule_once(lambda dt: self._show_status(str(e), error=True), 0)

    def _show_status(self, msg: str, error: bool = False):
        # Plus d'affichage en bas — le toast central auto-dismiss suffit.
        # On garde la propriété status_text vide pour ne pas casser les bindings,
        # mais le Label en bas n'est plus utilisé.
        self.status_text  = ""
        self.status_color = [0.9, 0.2, 0.2, 1] if error else [0.0, 0.85, 0.4, 1]
        try:
            from screens.toast import show_toast
            level = "error" if error else "success"
            show_toast(msg, level=level, duration=3.5)
        except (ImportError, Exception):
            # Fallback : si toast échoue (ex: import problem), on remet
            # le message dans status_text comme avant.
            self.status_text = msg
