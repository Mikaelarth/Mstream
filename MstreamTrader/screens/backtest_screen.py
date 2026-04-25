"""
MstreamTrader - Écran Backtest UI
====================================

Permet de lancer un backtest depuis l'app Kivy (Android & desktop) sans
passer par la CLI. Saisie : jours, capital, coins. Sortie : rapport résumé
(Sharpe, ROI, win rate, max DD).

Utilise core/backtest.py en mode synchrone (lance dans un thread daemon
pour ne pas bloquer l'UI Kivy).
"""

from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.properties import StringProperty, ListProperty
from kivy.metrics import dp
from kivy.clock import Clock


class BacktestScreen(Screen):
    """
    Écran Backtest : saisir paramètres + lancer + voir rapport.
    """
    status_text       = StringProperty("Prêt à lancer un backtest")
    status_color      = ListProperty([0.6, 0.6, 0.6, 1])
    report_summary    = StringProperty("Aucun backtest lancé")
    is_running        = False

    def on_enter(self):
        self._build_ui()

    def _build_ui(self):
        if self.children:
            return   # déjà construit

        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))

        # Header
        root.add_widget(Label(
            text="[b]Backtest Engine[/b]",
            markup=True, font_size=dp(20),
            size_hint_y=None, height=dp(40),
            color=(0.9, 0.9, 1, 1),
        ))

        # Inputs
        inputs = BoxLayout(orientation="vertical", spacing=dp(6),
                            size_hint_y=None, height=dp(220))

        inputs.add_widget(Label(
            text="Jours d'historique (7 à 365) :",
            font_size=dp(13), size_hint_y=None, height=dp(22),
        ))
        self._days_input = TextInput(
            text="60", multiline=False, input_filter="int",
            size_hint_y=None, height=dp(36),
        )
        inputs.add_widget(self._days_input)

        inputs.add_widget(Label(
            text="Capital initial USDT :",
            font_size=dp(13), size_hint_y=None, height=dp(22),
        ))
        self._capital_input = TextInput(
            text="1000", multiline=False, input_filter="float",
            size_hint_y=None, height=dp(36),
        )
        inputs.add_widget(self._capital_input)

        inputs.add_widget(Label(
            text="Coins (séparés par virgule) :",
            font_size=dp(13), size_hint_y=None, height=dp(22),
        ))
        self._coins_input = TextInput(
            text="bitcoin,ethereum,solana", multiline=False,
            size_hint_y=None, height=dp(36),
        )
        inputs.add_widget(self._coins_input)

        root.add_widget(inputs)

        # Bouton Lancer
        run_btn = Button(
            text="Lancer Backtest",
            size_hint_y=None, height=dp(50),
            background_color=(0.0, 0.55, 0.85, 1),
            font_size=dp(15),
            bold=True,
        )
        run_btn.bind(on_press=lambda *_: self._start_backtest())
        root.add_widget(run_btn)

        # Status
        self._status_label = Label(
            text=self.status_text,
            size_hint_y=None, height=dp(24),
            font_size=dp(11), color=(0.7, 0.7, 0.7, 1),
        )
        root.add_widget(self._status_label)

        # Rapport (scrollable)
        scroll = ScrollView()
        self._report_label = Label(
            text=self.report_summary, font_size=dp(12),
            size_hint_y=None, halign="left", valign="top",
            color=(0.85, 0.85, 0.95, 1),
        )
        self._report_label.bind(
            texture_size=lambda inst, val: setattr(inst, "height", val[1]),
        )
        self._report_label.bind(
            width=lambda inst, val: setattr(inst, "text_size", (val, None)),
        )
        scroll.add_widget(self._report_label)
        root.add_widget(scroll)

        # Navigation footer
        nav = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(4))
        for label, screen in [("Dashboard", "dashboard"),
                                ("Signaux", "signals"),
                                ("Portfolio", "portfolio"),
                                ("Config", "settings")]:
            b = Button(text=label, font_size=dp(12))
            b.bind(on_press=lambda inst, s=screen: self._navigate(s))
            nav.add_widget(b)
        root.add_widget(nav)

        self.add_widget(root)

    def _navigate(self, screen_name):
        from kivy.app import App
        App.get_running_app().root.current = screen_name

    def _start_backtest(self):
        if self.is_running:
            self._update_status("Un backtest est déjà en cours…", error=True)
            return
        try:
            days     = int(self._days_input.text)
            capital  = float(self._capital_input.text)
            coins    = [c.strip() for c in self._coins_input.text.split(",") if c.strip()]
            if days < 7 or days > 365:
                raise ValueError("Jours doit être entre 7 et 365")
            if capital <= 0:
                raise ValueError("Capital doit être > 0")
            if not coins:
                raise ValueError("Liste de coins vide")
        except ValueError as exc:
            self._update_status(f"Saisie invalide : {exc}", error=True)
            return

        from threading import Thread
        self.is_running = True
        self._update_status("Téléchargement des données…", error=False)
        self.report_summary = "Backtest en cours, patientez (~15-30 secondes)..."
        self._update_report_label()
        Thread(target=self._run_backtest_async,
               args=(days, capital, coins),
               daemon=True).start()

    def _run_backtest_async(self, days: int, capital: float, coins: list):
        try:
            from core import market_data
            from core.backtest import Backtest, BacktestConfig

            coins_data = {}
            for cid in coins:
                d = market_data.get_ohlcv_for_analysis(cid, days=days, interval="1h")
                if d and len(d) >= 60:
                    coins_data[cid] = d

            if not coins_data:
                Clock.schedule_once(lambda dt: self._show_error("Aucune donnée téléchargée"), 0)
                return

            # Backtest "validation stratégie" : on relâche les filtres
            # secondaires (ensemble, mtf, correlation) pour permettre à la
            # stratégie de base de s'exprimer sur historique court.
            # Le bot LIVE conserve tous les filtres pour la rigueur.
            cfg = BacktestConfig(
                initial_capital=capital,
                candle_duration_sec=3600,
                periods_per_year=8760,
                cooldown_candles=6,
                # Seuils permissifs pour démontrer la stratégie de base
                min_score=25.0,
                min_confidence=30.0,
                min_rr=1.5,
                # Filtres avancés OFF pour avoir des trades en backtest
                # (le bot LIVE les garde ON)
                use_ensemble=False,
                use_mtf_confluence=False,
                use_correlation_block=False,
            )
            bt = Backtest(cfg)
            result = bt.run(coins_data)
            r = result.report

            # Calcul du warmup (60 candles 1h = 2.5j)
            warmup_days = (cfg.warmup_candles * cfg.candle_duration_sec) / 86400

            summary = (
                f"Backtest terminé\n\n"
                f"PÉRIODE\n"
                f"Demandée       : {days} jours\n"
                f"Warmup (skip)  : {warmup_days:.1f} jours (calcul indicateurs)\n"
                f"Tradée réelle  : {result.duration_days:.1f} jours\n\n"
                f"CAPITAL\n"
                f"Initial        : ${r['initial_capital']:,.2f}\n"
                f"Final          : ${r['final_capital']:,.2f}\n"
                f"Rendement total: {r['total_return_pct']:+.2f}%\n"
                f"Annualisé      : {r['annualized_return']:+.2f}%\n\n"
                f"RATIOS RISK-ADJUSTED\n"
                f"Sharpe         : {r['sharpe']:.3f}\n"
                f"Sortino        : {r['sortino']:.3f}\n"
                f"Calmar         : {r['calmar']:.3f}\n"
                f"Max Drawdown   : {r['max_drawdown_pct']:.2f}%\n\n"
                f"TRADES\n"
                f"Total          : {r['total_trades']}\n"
                f"Wins / Losses  : {r['winners']} / {r['losers']}\n"
                f"Win rate       : {r['win_rate_pct']:.2f}%\n"
                f"Profit factor  : {r['profit_factor']:.3f}\n"
                f"Expectancy     : ${r['expectancy_usdt']:+.2f}/trade\n\n"
                f"R-MULTIPLES\n"
                f"R-multiple avg : {r['r_avg']:+.3f}\n"
                f"R best / worst : {r['r_best']:+.2f} / {r['r_worst']:+.2f}\n\n"
                f"Sorties par raison : {result.closed_by_reason}\n"
            )

            # Si AUCUN trade, l'utilisateur a besoin de comprendre POURQUOI
            if r['total_trades'] == 0:
                summary += (
                    "\n[!] AUCUN TRADE EXÉCUTÉ\n"
                    "Causes possibles :\n"
                    "  - Critères trop stricts (R/R min, score min)\n"
                    "  - Régime de marché défavorable (filtre profile)\n"
                    "  - Données insuffisantes ou volatilité trop faible\n"
                    "Voir les rejets ci-dessous pour comprendre.\n"
                )

            if result.rejections_by_filter:
                summary += "\nFiltres (rejets) :\n"
                total_rejets = sum(result.rejections_by_filter.values())
                for k, v in sorted(result.rejections_by_filter.items(), key=lambda x: -x[1]):
                    pct = (v / total_rejets * 100) if total_rejets else 0
                    summary += f"  {k:<25}: {v}  ({pct:.0f}%)\n"

            Clock.schedule_once(lambda dt: self._show_success(summary), 0)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            Clock.schedule_once(lambda dt: self._show_error(f"Erreur : {exc}"), 0)
        finally:
            Clock.schedule_once(lambda dt: setattr(self, "is_running", False), 0)

    def _show_success(self, text: str):
        self._update_status("Backtest terminé", error=False)
        self.report_summary = text
        self._update_report_label()

    def _show_error(self, text: str):
        # On affiche l'erreur dans le status uniquement, pas dans le rapport
        # (évitait le doublon "Aucune donnée téléchargée" en bas)
        self._update_status(text, error=True)
        self.report_summary = "Aucun rapport — relancez après vérification."
        self._update_report_label()

    def _update_status(self, text: str, error: bool = False):
        self.status_text = text
        if hasattr(self, "_status_label"):
            self._status_label.text = text
            self._status_label.color = [0.9, 0.3, 0.3, 1] if error else [0.6, 0.85, 0.6, 1]

    def _update_report_label(self):
        if hasattr(self, "_report_label"):
            self._report_label.text = self.report_summary
