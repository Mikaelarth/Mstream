"""
MstreamTrader - Écran Signaux de Trading
Affiche tous les signaux avec leur score, confiance, stop-loss, take-profit
"""

from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.clock import Clock
from kivy.properties import StringProperty, ListProperty
from kivy.metrics import dp

from core.signals import Signal, SIGNAL_LABELS


class SignalCard(BoxLayout):
    """Carte individuelle pour un signal de trading."""

    def __init__(self, signal_obj, on_trade_callback=None, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.signal_obj = signal_obj
        self.on_trade_callback = on_trade_callback
        self.padding  = [dp(12), dp(10)]
        self.spacing  = dp(6)
        self.size_hint_y = None
        self.height = dp(180)

        # Couleur de fond selon le signal
        from kivy.graphics import Color, RoundedRectangle
        with self.canvas.before:
            Color(*self._bg_color())
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
        self.bind(pos=self._update_rect, size=self._update_rect)

        self._build()

    def _bg_color(self):
        s = self.signal_obj.signal
        if s == Signal.STRONG_BUY:  return (0.0, 0.35, 0.15, 1)
        if s == Signal.BUY:         return (0.0, 0.28, 0.12, 1)
        if s == Signal.STRONG_SELL: return (0.35, 0.05, 0.05, 1)
        if s == Signal.SELL:        return (0.28, 0.08, 0.05, 1)
        return (0.18, 0.18, 0.22, 1)

    def _update_rect(self, *_):
        self._rect.pos  = self.pos
        self._rect.size = self.size

    def _build(self):
        s = self.signal_obj

        # Ligne 1: Symbole + Signal badge
        row1 = BoxLayout(size_hint_y=None, height=dp(32))
        row1.add_widget(Label(
            text=f"[b]{s.symbol}[/b]",
            markup=True, font_size=dp(20), halign="left",
            size_hint_x=0.4, color=(1, 1, 1, 1)
        ))
        signal_lbl = Label(
            text=f"[b]{s.signal_label}[/b]",
            markup=True, font_size=dp(13),
            color=list(s.color), halign="right", size_hint_x=0.6
        )
        row1.add_widget(signal_lbl)
        self.add_widget(row1)

        # Ligne 2: Prix + Confiance
        from core.market_data import format_price
        row2 = BoxLayout(size_hint_y=None, height=dp(24))
        row2.add_widget(Label(
            text=format_price(s.price),
            font_size=dp(16), halign="left",
            color=(0.9, 0.9, 0.9, 1), size_hint_x=0.5
        ))
        row2.add_widget(Label(
            text=f"Confiance: {s.confidence:.0f}%",
            font_size=dp(13), halign="right",
            color=(0.7, 0.7, 0.7, 1), size_hint_x=0.5
        ))
        self.add_widget(row2)

        # Ligne 3: Stop-Loss / Take-Profit / R:R
        if s.stop_loss > 0:
            row3 = BoxLayout(size_hint_y=None, height=dp(22))
            row3.add_widget(Label(
                text=f"SL: {format_price(s.stop_loss)}",
                font_size=dp(11), color=(0.9, 0.3, 0.3, 1), halign="left", size_hint_x=0.33
            ))
            row3.add_widget(Label(
                text=f"TP: {format_price(s.take_profit)}",
                font_size=dp(11), color=(0.3, 0.9, 0.5, 1), halign="center", size_hint_x=0.34
            ))
            row3.add_widget(Label(
                text=f"R/R: {s.risk_reward:.1f}x",
                font_size=dp(11), color=(0.7, 0.85, 1, 1), halign="right", size_hint_x=0.33
            ))
            self.add_widget(row3)

        # Ligne 4: Raisons principales (max 2)
        top_reasons = s.reasons[:2] if s.reasons else []
        for reason in top_reasons:
            short = reason[:55] + "…" if len(reason) > 55 else reason
            self.add_widget(Label(
                text=f"• {short}",
                font_size=dp(10), color=(0.65, 0.65, 0.65, 1),
                halign="left", size_hint_y=None, height=dp(16),
                text_size=(None, None)
            ))

        # Bouton Trader (si achat/vente fort)
        if s.signal in (Signal.STRONG_BUY, Signal.BUY, Signal.SELL, Signal.STRONG_SELL):
            btn_color = (0.0, 0.7, 0.35, 1) if s.signal in (Signal.BUY, Signal.STRONG_BUY) \
                        else (0.8, 0.15, 0.15, 1)
            btn_text  = f"ACHETER {s.symbol}" if s.signal in (Signal.BUY, Signal.STRONG_BUY) \
                        else f"VENDRE {s.symbol}"
            btn = Button(
                text=btn_text,
                size_hint_y=None, height=dp(32),
                background_color=btn_color,
                font_size=dp(12), bold=True
            )
            btn.bind(on_press=lambda *_: self.on_trade_callback and self.on_trade_callback(s))
            self.add_widget(btn)


class SignalsScreen(Screen):
    filter_text  = StringProperty("TOUS")
    count_text   = StringProperty("0 signaux")

    FILTERS = ["TOUS", "ACHAT FORT", "ACHAT", "CONSERVER", "VENTE", "VENTE FORTE"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._all_signals = []
        self._current_filter = "TOUS"

    def on_enter(self):
        self._refresh_from_app()

    def _refresh_from_app(self):
        app = self._get_app()
        if app and hasattr(app, "dashboard_screen"):
            self._all_signals = app.dashboard_screen.get_signals()
            self._render_signals()

    def _get_app(self):
        from kivy.app import App
        return App.get_running_app()

    def set_filter(self, f: str):
        self._current_filter = f
        self.filter_text = f
        self._render_signals()

    def _render_signals(self):
        if not hasattr(self.ids, "signals_grid"):
            return

        grid = self.ids.signals_grid
        grid.clear_widgets()

        filtered = self._filtered_signals()
        self.count_text = f"{len(filtered)} signal{'s' if len(filtered)>1 else ''}"

        for sig in filtered:
            card = SignalCard(sig, on_trade_callback=self._open_trade_dialog)
            grid.add_widget(card)

        if not filtered:
            grid.add_widget(Label(
                text="Aucun signal — Actualisation en cours…",
                color=(0.5, 0.5, 0.5, 1), font_size=dp(14),
                size_hint_y=None, height=dp(60)
            ))

    def _filtered_signals(self):
        if self._current_filter == "TOUS":
            return self._all_signals
        reverse_map = {v: k for k, v in SIGNAL_LABELS.items()}
        target = reverse_map.get(self._current_filter)
        if target:
            return [s for s in self._all_signals if s.signal == target]
        return self._all_signals

    def _open_trade_dialog(self, signal_obj):
        app = self._get_app()
        if app:
            app.open_trade_dialog(signal_obj)

    def refresh(self, signals_list: list):
        self._all_signals = signals_list
        self._render_signals()
