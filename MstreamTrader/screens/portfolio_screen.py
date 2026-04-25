"""
MstreamTrader - Écran Portefeuille
Affiche les positions, PnL en temps réel, historique des trades
et le suivi des deux portefeuilles automatiques (Sécurité & Libre)
"""

from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.properties import StringProperty, ListProperty
from kivy.metrics import dp
from kivy.clock import Clock

from core import database
from core.market_data import format_price


class PortfolioScreen(Screen):
    total_value_text = StringProperty("$0.00")
    total_pnl_text   = StringProperty("+$0.00")
    pnl_color        = ListProperty([0.0, 0.85, 0.4, 1])
    usdt_balance     = StringProperty("$0.00")
    win_rate_text    = StringProperty("0%")
    total_trades_text= StringProperty("0")
    pnl_total_text   = StringProperty("$0.00")

    # Bot Maître
    master_active_text  = StringProperty("OFF")
    master_active_color = ListProperty([0.5, 0.5, 0.5, 1])
    master_capital_text = StringProperty("$0.00")
    master_roi_text     = StringProperty("+0.00%")
    master_roi_color    = ListProperty([0.0, 0.85, 0.4, 1])
    master_positions    = StringProperty("0 position(s)")
    master_pnl_text     = StringProperty("+$0.00")
    master_pnl_color    = ListProperty([0.0, 0.85, 0.4, 1])
    auto_status_text    = StringProperty("Bot Maître inactif")

    # Agent adaptatif (V12) — visibilité utilisateur
    adaptive_summary    = StringProperty("Agent adaptatif inactif")
    adaptive_strategies = StringProperty("")
    adaptive_profile    = StringProperty("")

    # Anciens portefeuilles (legacy)
    securite_info     = StringProperty("Budget: $0  |  Positions: 0  |  PnL: $0.00")
    securite_active   = StringProperty("OFF")
    securite_color    = ListProperty([0.5, 0.5, 0.5, 1])
    libre_info        = StringProperty("Budget: $0  |  Positions: 0  |  PnL: $0.00")
    libre_active      = StringProperty("OFF")
    libre_color       = ListProperty([0.5, 0.5, 0.5, 1])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._prices = {}

    def on_enter(self):
        self._refresh()

    def _refresh(self):
        app = self._get_app()
        if app and hasattr(app, "dashboard_screen"):
            self._prices = app.dashboard_screen.get_prices()
        self._update_ui()

    def _get_app(self):
        from kivy.app import App
        return App.get_running_app()

    def _update_ui(self):
        # Solde
        balance = float(database.get_setting("usdt_balance", "0"))
        self.usdt_balance = f"${balance:,.2f}"

        # Portefeuille
        pv = database.calculate_portfolio_value(self._prices)
        self.total_value_text = f"${pv['total_value']:,.2f}"
        pnl = pv["total_pnl"]
        self.total_pnl_text = f"{'+'if pnl>=0 else ''}{pnl:,.2f} USDT ({pv['total_pnl_pct']:+.1f}%)"
        self.pnl_color = [0.0, 0.85, 0.4, 1] if pnl >= 0 else [0.9, 0.2, 0.2, 1]

        # Stats
        stats = database.get_trade_stats()
        self.win_rate_text     = f"{stats['win_rate']}%"
        self.total_trades_text = str(stats["total"])
        tpnl = stats["total_pnl"]
        self.pnl_total_text = f"{'+'if tpnl>=0 else ''}{tpnl:,.2f} $"

        # Bot Maître + auto-trader summary
        self._update_master_summary()
        self._update_auto_summary()

        # Positions
        self._render_positions(pv["positions"])

        # Historique
        self._render_history()

        # Positions auto
        self._render_auto_positions()

        # Journal auto
        self._render_auto_log()

    def _update_master_summary(self):
        """Met à jour le tableau de bord du Bot Maître."""
        is_active = database.get_setting("auto_trade_master", "false") == "true"
        budget    = float(database.get_setting("budget_master", "0"))
        initial   = float(database.get_setting("budget_master_initial", "0"))

        if is_active:
            self.master_active_text  = "ACTIF"
            self.master_active_color = [0.0, 0.85, 0.4, 1]
        else:
            self.master_active_text  = "INACTIF"
            self.master_active_color = [0.5, 0.5, 0.5, 1]

        self.master_capital_text = f"${budget:,.2f}"

        if initial > 0:
            roi = (budget - initial) / initial * 100
            self.master_roi_text  = f"{roi:+.2f}%"
            self.master_roi_color = [0.0, 0.85, 0.4, 1] if roi >= 0 else [0.9, 0.2, 0.2, 1]
        else:
            self.master_roi_text  = "+0.00%"
            self.master_roi_color = [0.5, 0.5, 0.5, 1]

        summary = database.get_auto_portfolio_summary("master", self._prices)
        pos_count = summary["open_count"]
        self.master_positions = f"{pos_count} position{'s' if pos_count != 1 else ''} ouverte{'s' if pos_count != 1 else ''}"

        upnl = summary["unrealized_pnl"]
        self.master_pnl_text  = f"{'+' if upnl >= 0 else ''}{upnl:,.2f} $"
        self.master_pnl_color = [0.0, 0.85, 0.4, 1] if upnl >= 0 else [0.9, 0.2, 0.2, 1]

        try:
            from core.auto_trader import get_auto_trader
            self.auto_status_text = get_auto_trader().get_status()
        except (ImportError, AttributeError):
            self.auto_status_text = "Bot Maître non démarré"

        # ── Agent adaptatif : stats visibles au user (V12) ──
        try:
            from core.adaptive import get_adaptive_agent
            agent = get_adaptive_agent()
            total_t = agent.get_total_trades()
            if total_t == 0:
                self.adaptive_summary = "Agent adaptatif : 0 trade observé (cold start)"
                self.adaptive_strategies = ""
                self.adaptive_profile = ""
            else:
                regime_str = "bull"   # par défaut, on lit ce qu'on a
                try:
                    regime, _ = get_auto_trader().get_regime()
                    regime_str = regime.value
                except (ImportError, AttributeError):
                    pass
                summary = agent.get_summary(regime_str)
                means = summary["strategy_means"]
                self.adaptive_summary = (
                    f"Agent adaptatif : {total_t} trades observés (régime {regime_str.upper()})"
                )
                self.adaptive_strategies = (
                    f"Trend {means.get('trend_follower', 0.5):.2f} | "
                    f"Reversion {means.get('mean_reversion', 0.5):.2f} | "
                    f"Breakout {means.get('breakout_hunter', 0.5):.2f}"
                )
                best = summary.get("best_profile") or "balanced (cold start)"
                self.adaptive_profile = f"Profil suggéré : {best}"
        except (ImportError, AttributeError, KeyError):
            self.adaptive_summary = "Agent adaptatif : indisponible"

    def export_trades_csv(self):
        """Bouton 'Export CSV' — exporte tous les trades."""
        from threading import Thread
        Thread(target=self._do_export_csv, daemon=True).start()

    def _do_export_csv(self):
        try:
            from core.export import export_trades_to_csv
            path = export_trades_to_csv()
            msg = f"Export OK : {path.name}" if path else "Aucun trade à exporter"
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: setattr(self, "auto_status_text", msg), 0)
        except (ImportError, OSError) as exc:
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: setattr(self, "auto_status_text", f"Export failed: {exc}"), 0)

    def _update_auto_summary(self):
        """Met à jour le résumé des portefeuilles automatiques."""
        for ptype, attr_info, attr_active, attr_color in [
            ("securite", "securite_info", "securite_active", "securite_color"),
            ("libre",    "libre_info",    "libre_active",    "libre_color"),
        ]:
            is_active = database.get_setting(f"auto_trade_{ptype}", "false") == "true"
            budget    = float(database.get_setting(f"budget_{ptype}", "0"))
            summary   = database.get_auto_portfolio_summary(ptype, self._prices)
            pnl       = summary["unrealized_pnl"]
            sign      = "+" if pnl >= 0 else ""

            setattr(self, attr_info,
                f"Budget: ${budget:,.0f}  |  "
                f"Positions: {summary['open_count']}  |  "
                f"PnL: {sign}${pnl:,.2f}"
            )
            if is_active:
                setattr(self, attr_active, "ON")
                setattr(self, attr_color,  [0.0, 0.85, 0.4, 1])
            else:
                setattr(self, attr_active, "OFF")
                setattr(self, attr_color,  [0.5, 0.5, 0.5, 1])

        # Statut global de l'auto-trader
        try:
            from core.auto_trader import get_auto_trader
            self.auto_status_text = get_auto_trader().get_status()
        except Exception:
            self.auto_status_text = "Auto-trader non démarré"

    def _render_positions(self, positions: list):
        if not hasattr(self.ids, "positions_grid"):
            return
        grid = self.ids.positions_grid
        grid.clear_widgets()

        if not positions:
            grid.add_widget(Label(
                text="Aucune position ouverte",
                color=(0.5, 0.5, 0.5, 1), font_size=dp(14),
                size_hint_y=None, height=dp(50)
            ))
            return

        for pos in positions:
            card = self._build_position_card(pos)
            grid.add_widget(card)

    def _build_position_card(self, pos: dict) -> BoxLayout:
        from kivy.graphics import Color, RoundedRectangle

        pnl       = pos.get("pnl", 0)
        pnl_pct   = pos.get("pnl_pct", 0)
        is_profit = pnl >= 0

        card = BoxLayout(
            orientation="vertical",
            size_hint_y=None, height=dp(100),
            padding=[dp(12), dp(8)], spacing=dp(4)
        )
        with card.canvas.before:
            bg_color = (0.0, 0.22, 0.10, 1) if is_profit else (0.22, 0.05, 0.05, 1)
            Color(*bg_color)
            r = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(8)])
            card.bind(pos=lambda *_: setattr(r, "pos", card.pos),
                      size=lambda *_: setattr(r, "size", card.size))

        # Ligne 1 : Symbole + Valeur actuelle
        row1 = BoxLayout(size_hint_y=None, height=dp(28))
        row1.add_widget(Label(
            text=f"[b]{pos['symbol']}[/b]",
            markup=True, font_size=dp(18), color=(1, 1, 1, 1),
            halign="left", size_hint_x=0.5
        ))
        row1.add_widget(Label(
            text=f"${pos['current_value']:,.2f}",
            font_size=dp(16), color=(1, 1, 1, 1),
            halign="right", size_hint_x=0.5
        ))
        card.add_widget(row1)

        # Ligne 2 : Quantité + Prix moyen
        row2 = BoxLayout(size_hint_y=None, height=dp(20))
        row2.add_widget(Label(
            text=f"Qté: {pos['quantity']:.6f}",
            font_size=dp(11), color=(0.7, 0.7, 0.7, 1),
            halign="left", size_hint_x=0.5
        ))
        row2.add_widget(Label(
            text=f"Achat moy: {format_price(pos['avg_buy'])}",
            font_size=dp(11), color=(0.7, 0.7, 0.7, 1),
            halign="right", size_hint_x=0.5
        ))
        card.add_widget(row2)

        # Ligne 3 : PnL
        pnl_color = (0.0, 0.85, 0.4, 1) if is_profit else (0.9, 0.2, 0.2, 1)
        pnl_sign  = "+" if pnl >= 0 else ""
        row3 = BoxLayout(size_hint_y=None, height=dp(22))
        row3.add_widget(Label(
            text=f"PnL: {pnl_sign}{pnl:,.2f} $ ({pnl_pct:+.1f}%)",
            font_size=dp(13), color=pnl_color, halign="left"
        ))
        row3.add_widget(Label(
            text=f"Investi: ${pos['invested']:,.2f}",
            font_size=dp(11), color=(0.6, 0.6, 0.6, 1),
            halign="right", size_hint_x=0.4
        ))
        card.add_widget(row3)

        return card

    def _render_history(self):
        if not hasattr(self.ids, "history_grid"):
            return
        grid = self.ids.history_grid
        grid.clear_widgets()

        trades = database.get_trades(limit=30)
        if not trades:
            grid.add_widget(Label(
                text="Aucun trade effectué",
                color=(0.5, 0.5, 0.5, 1), font_size=dp(13),
                size_hint_y=None, height=dp(40)
            ))
            return

        for trade in trades:
            row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(4))
            side_color = (0.0, 0.85, 0.4, 1) if trade["side"] == "BUY" else (0.9, 0.2, 0.2, 1)
            row.add_widget(Label(text=trade["symbol"], font_size=dp(12), size_hint_x=0.15, color=(1,1,1,1)))
            row.add_widget(Label(text=trade["side"], font_size=dp(11), size_hint_x=0.12, color=side_color))
            row.add_widget(Label(text=f"{trade['quantity']:.4f}", font_size=dp(11), size_hint_x=0.2, color=(0.8,0.8,0.8,1)))
            row.add_widget(Label(text=format_price(trade["price"]), font_size=dp(11), size_hint_x=0.25, color=(0.8,0.8,0.8,1)))
            row.add_widget(Label(text=trade["executed_at"][:10], font_size=dp(10), size_hint_x=0.28, color=(0.5,0.5,0.5,1)))
            grid.add_widget(row)

    def _render_auto_positions(self):
        """Affiche les positions ouvertes des deux portefeuilles automatiques."""
        if not hasattr(self.ids, "auto_positions_grid"):
            return
        grid = self.ids.auto_positions_grid
        grid.clear_widgets()

        all_pos = database.get_all_open_positions()
        if not all_pos:
            grid.add_widget(Label(
                text="Aucune position auto ouverte",
                color=(0.5, 0.5, 0.5, 1), font_size=dp(12),
                size_hint_y=None, height=dp(36)
            ))
            return

        for pos in all_pos:
            price  = self._prices.get(pos["coin_id"], {}).get("price", pos["entry_price"])
            pnl    = (price - pos["entry_price"]) * pos["quantity"]
            ptype  = pos["portfolio_type"].upper()
            pcolor = (0.0, 0.85, 0.4, 1) if pnl >= 0 else (0.9, 0.2, 0.2, 1)
            badge_color = (0.1, 0.4, 0.9, 1) if pos["portfolio_type"] == "securite" else (0.9, 0.5, 0.1, 1)

            row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6),
                            padding=[dp(6), dp(4)])
            row.add_widget(Label(text=f"[b]{pos['symbol']}[/b]", markup=True,
                                 font_size=dp(13), size_hint_x=0.16, color=(1,1,1,1)))
            row.add_widget(Label(text=ptype, font_size=dp(10), size_hint_x=0.16,
                                 color=badge_color))
            row.add_widget(Label(text=f"@{format_price(pos['entry_price'])}", font_size=dp(10),
                                 size_hint_x=0.22, color=(0.7,0.7,0.7,1)))
            row.add_widget(Label(text=f"SL:{format_price(pos['stop_loss'])}", font_size=dp(10),
                                 size_hint_x=0.22, color=(0.9, 0.3, 0.3, 1)))
            row.add_widget(Label(text=f"{'+' if pnl >= 0 else ''}{pnl:,.2f}$",
                                 font_size=dp(12), size_hint_x=0.24, color=pcolor))
            grid.add_widget(row)

    def _render_auto_log(self):
        """Affiche le journal des 20 dernières actions de l'auto-trader."""
        if not hasattr(self.ids, "auto_log_grid"):
            return
        grid = self.ids.auto_log_grid
        grid.clear_widgets()

        logs = database.get_auto_trader_logs(limit=20)
        if not logs:
            grid.add_widget(Label(
                text="Journal vide — Aucune action auto enregistrée",
                color=(0.5, 0.5, 0.5, 1), font_size=dp(12),
                size_hint_y=None, height=dp(36)
            ))
            return

        action_colors = {
            "ENTRY":    (0.0, 0.85, 0.4, 1),
            "EXIT_TP":  (0.4, 0.8, 1.0, 1),
            "EXIT_SL":  (0.9, 0.3, 0.3, 1),
            "SKIP":     (0.6, 0.6, 0.2, 1),
            "ERROR":    (1.0, 0.2, 0.2, 1),
        }

        for entry in logs:
            color  = action_colors.get(entry["action"], (0.7, 0.7, 0.7, 1))
            ptype  = entry["portfolio_type"][:3].upper()
            sym    = entry["symbol"] or "—"
            action = entry["action"]
            ts     = entry["logged_at"][11:16]

            row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(4),
                            padding=[dp(4), dp(2)])
            row.add_widget(Label(text=ts, font_size=dp(10), size_hint_x=0.14,
                                 color=(0.5,0.5,0.5,1)))
            row.add_widget(Label(text=ptype, font_size=dp(10), size_hint_x=0.12,
                                 color=(0.7,0.7,0.7,1)))
            row.add_widget(Label(text=f"[b]{action}[/b]", markup=True,
                                 font_size=dp(10), size_hint_x=0.18, color=color))
            row.add_widget(Label(text=sym, font_size=dp(10), size_hint_x=0.16,
                                 color=(1,1,1,1)))
            reason_short = entry["reason"][:28] + "…" if len(entry["reason"]) > 28 else entry["reason"]
            row.add_widget(Label(text=reason_short, font_size=dp(10), size_hint_x=0.40,
                                 color=(0.55,0.55,0.55,1), halign="left"))
            grid.add_widget(row)

    def refresh(self, prices: dict):
        self._prices = prices
        self._update_ui()
