"""
MstreamTrader - Point d'entrée principal
Application de trading crypto Kivy — Android & Desktop
"""

import os
import sys

# Assurer que les modules core/ et screens/ sont accessibles
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, FadeTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.core.window import Window

from core import database
from core.market_data import format_price
from core import exchange
from core.signals import Signal
from core.auto_trader import get_auto_trader
from core.logging_setup import setup_logging

# Activation du logger rotatif fichier dès le démarrage.
# console=False car Kivy capture sys.stderr → un StreamHandler créerait une
# récursion infinie (kivy émet sur stderr → handler écrit sur stderr → kivy
# capture → ré-émet → ...). Kivy fournit sa propre sortie console.
setup_logging(console=False)

# ── Enregistrer une police compatible emoji ──────────────────────────────────
# La police Roboto par défaut de Kivy ne contient pas les glyphs emoji
# (📊 ⚡ 💼 ⚙ 🔬 ...). On enregistre "Segoe UI Emoji" sous Windows et
# "DejaVu Sans" / "Noto Color Emoji" sous Linux/Android comme alternative.
def _register_emoji_font():
    from kivy.core.text import LabelBase
    candidates = [
        # Windows : Segoe UI Emoji présent par défaut depuis Win 8.1
        r"C:\Windows\Fonts\seguiemj.ttf",
        # Linux / Android (si présent)
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/system/fonts/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                LabelBase.register(name="Roboto", fn_regular=p)
                return p
            except Exception:
                continue
    return None

_emoji_font = _register_emoji_font()

from screens.dashboard_screen import DashboardScreen
from screens.signals_screen   import SignalsScreen
from screens.portfolio_screen import PortfolioScreen
from screens.settings_screen  import SettingsScreen
from screens.backtest_screen  import BacktestScreen


# ── Charger les fichiers KV ──────────────────────────────────────────────────
KV_DIR = os.path.join(BASE_DIR, "kv")
for kv_file in ["dashboard.kv", "signals.kv", "portfolio.kv", "settings.kv"]:
    path = os.path.join(KV_DIR, kv_file)
    if os.path.exists(path):
        Builder.load_file(path)


# ── Widget liste de coins (utilisé dans dashboard.kv) ────────────────────────
class CoinListWidget(GridLayout):
    """Affiche la liste des cryptos avec prix et signal en temps réel."""

    def __init__(self, **kwargs):
        super().__init__(cols=1, **kwargs)
        self._rows = {}

    def refresh(self, prices: dict, signals: list):
        self.clear_widgets()
        self._rows = {}

        # Mapper coin_id -> signal
        sig_map = {s.coin_id: s for s in signals}

        from core.market_data import DEFAULT_COINS
        for coin_def in DEFAULT_COINS:
            cid    = coin_def["id"]
            symbol = coin_def["symbol"]
            name   = coin_def["name"]

            pdata  = prices.get(cid, {})
            price  = pdata.get("price", 0)
            chg24  = pdata.get("change_24h", 0)
            sig    = sig_map.get(cid)

            row = self._build_row(cid, symbol, name, price, chg24, sig)
            self.add_widget(row)

    def _build_row(self, cid, symbol, name, price, chg24, sig) -> BoxLayout:
        from kivy.graphics import Color, RoundedRectangle

        row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None, height=dp(56),
            padding=[dp(10), dp(6)], spacing=dp(8)
        )
        with row.canvas.before:
            Color(0.12, 0.12, 0.18, 1)
            r = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(6)])
            row.bind(pos=lambda *_: setattr(r, "pos", row.pos),
                     size=lambda *_: setattr(r, "size", row.size))

        # Symbole
        row.add_widget(Label(
            text=f"[b]{symbol}[/b]\n[size=10][color=888888]{name}[/color][/size]",
            markup=True, font_size=dp(14), size_hint_x=0.22, halign="left",
            color=(1, 1, 1, 1)
        ))

        # Prix
        row.add_widget(Label(
            text=format_price(price),
            font_size=dp(14), size_hint_x=0.28, halign="right",
            color=(1, 1, 1, 1)
        ))

        # Variation 24h
        chg_color = (0.0, 0.85, 0.4, 1) if chg24 >= 0 else (0.9, 0.2, 0.2, 1)
        row.add_widget(Label(
            text=f"{chg24:+.2f}%",
            font_size=dp(13), size_hint_x=0.22, halign="right",
            color=chg_color
        ))

        # Signal badge
        if sig:
            from core.signals import SIGNAL_LABELS
            sig_label = SIGNAL_LABELS[sig.signal][:5]
            row.add_widget(Label(
                text=f"[b]{sig_label}[/b]\n[size=9]{sig.confidence:.0f}%[/size]",
                markup=True, font_size=dp(11), size_hint_x=0.28, halign="right",
                color=list(sig.color)
            ))
        else:
            row.add_widget(Label(text="", size_hint_x=0.28))

        return row


# ── Dialogue de Trade ─────────────────────────────────────────────────────────
class TradeDialog(Popup):
    """Popup pour confirmer et exécuter un trade."""

    def __init__(self, signal_obj, **kwargs):
        super().__init__(**kwargs)
        self.signal_obj = signal_obj
        self.title = f"{'ACHETER' if signal_obj.signal in (Signal.BUY, Signal.STRONG_BUY) else 'VENDRE'} {signal_obj.symbol}"
        self.size_hint = (0.92, 0.75)
        self._build()

    def _build(self):
        s = self.signal_obj
        is_buy = s.signal in (Signal.BUY, Signal.STRONG_BUY)

        layout = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))

        # Infos signal
        layout.add_widget(Label(
            text=f"Signal: [b]{s.signal_label}[/b]  Confiance: {s.confidence:.0f}%",
            markup=True, font_size=dp(14), size_hint_y=None, height=dp(28),
            color=list(s.color)
        ))
        layout.add_widget(Label(
            text=f"Prix actuel: {format_price(s.price)}",
            font_size=dp(13), size_hint_y=None, height=dp(24)
        ))
        if s.stop_loss:
            layout.add_widget(Label(
                text=f"Stop-Loss: {format_price(s.stop_loss)}   Take-Profit: {format_price(s.take_profit)}   R/R: {s.risk_reward}x",
                font_size=dp(11), size_hint_y=None, height=dp(22),
                color=(0.7, 0.7, 0.7, 1)
            ))

        # Montant USDT
        balance = float(database.get_setting("usdt_balance", "0"))
        risk_pct = float(database.get_setting("risk_per_trade", "2.0"))
        suggested = round(balance * risk_pct / 100, 2)

        layout.add_widget(Label(
            text=f"Montant à investir (USDT) — Solde: ${balance:,.2f}",
            font_size=dp(12), size_hint_y=None, height=dp(22),
            color=(0.6, 0.6, 0.6, 1)
        ))

        self._amount_input = TextInput(
            text=str(suggested),
            font_size=dp(16),
            size_hint_y=None, height=dp(44),
            input_filter="float", multiline=False,
            background_color=(0.15, 0.15, 0.20, 1),
            foreground_color=(1, 1, 1, 1)
        )
        layout.add_widget(self._amount_input)

        # Raisons
        reasons_text = "\n".join(f"• {r}" for r in s.reasons[:4])
        layout.add_widget(Label(
            text=reasons_text,
            font_size=dp(10), color=(0.55, 0.55, 0.55, 1),
            size_hint_y=None, height=dp(60), halign="left"
        ))

        self._status = Label(
            text="", font_size=dp(12),
            size_hint_y=None, height=dp(24)
        )
        layout.add_widget(self._status)

        # Boutons
        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        btn_color = (0.0, 0.65, 0.30, 1) if is_buy else (0.75, 0.1, 0.1, 1)
        confirm_btn = Button(
            text=f"✓ CONFIRMER",
            background_color=btn_color, font_size=dp(14), bold=True
        )
        confirm_btn.bind(on_press=self._execute_trade)
        cancel_btn = Button(
            text="✗ Annuler",
            background_color=(0.3, 0.3, 0.3, 1), font_size=dp(13)
        )
        cancel_btn.bind(on_press=lambda *_: self.dismiss())
        btns.add_widget(confirm_btn)
        btns.add_widget(cancel_btn)
        layout.add_widget(btns)

        self.content = layout

    def _execute_trade(self, *_):
        try:
            amount_usdt = float(self._amount_input.text)
        except ValueError:
            self._status.text = "Montant invalide"
            self._status.color = (0.9, 0.2, 0.2, 1)
            return

        if amount_usdt <= 0:
            self._status.text = "Montant doit être > 0"
            self._status.color = (0.9, 0.2, 0.2, 1)
            return

        self._status.text = "Exécution en cours…"
        self._status.color = (0.9, 0.75, 0.1, 1)

        from threading import Thread
        Thread(
            target=self._do_trade,
            args=(amount_usdt,),
            daemon=True
        ).start()

    def _do_trade(self, amount_usdt: float):
        client = exchange.get_client()
        if not client:
            # Mode sans Binance : trade manuel enregistré au prix CoinGecko
            from core.database import record_trade
            from core.signals import Signal as Sig
            s = self.signal_obj
            side = "BUY" if s.signal in (Sig.BUY, Sig.STRONG_BUY) else "SELL"
            qty = amount_usdt / s.price if s.price > 0 else 0
            record_trade(s.coin_id, s.symbol, side, qty, s.price,
                         fee=qty * s.price * 0.001, source="MANUAL_NO_EXCHANGE")
            Clock.schedule_once(lambda dt: self._trade_done(True, "Trade enregistré (sans exchange)"), 0)
        else:
            try:
                order = exchange.execute_signal_trade(self.signal_obj, amount_usdt)
                msg = f"Ordre {order.get('status','OK')} — ID: {order.get('order_id','')}"
                Clock.schedule_once(lambda dt: self._trade_done(True, msg), 0)
            except exchange.BinanceError as e:
                Clock.schedule_once(lambda dt: self._trade_done(False, str(e)), 0)

    def _trade_done(self, success: bool, msg: str):
        self._status.text  = msg
        self._status.color = (0.0, 0.85, 0.4, 1) if success else (0.9, 0.2, 0.2, 1)
        if success:
            Clock.schedule_once(lambda dt: self.dismiss(), 2)


# ── Application principale ───────────────────────────────────────────────────
class MstreamTraderApp(App):
    title = "Mstream Trader"

    def build(self):
        # Fond sombre
        Window.clearcolor = (0.07, 0.07, 0.10, 1)

        # Initialiser la base de données
        database.init_db()

        # Démarrer le moteur de trading autonome
        get_auto_trader().start()

        # Créer les écrans
        sm = ScreenManager(transition=FadeTransition(duration=0.15))

        self.dashboard_screen  = DashboardScreen(name="dashboard")
        self.signals_screen    = SignalsScreen(name="signals")
        self.portfolio_screen  = PortfolioScreen(name="portfolio")
        self.settings_screen   = SettingsScreen(name="settings")
        self.backtest_screen   = BacktestScreen(name="backtest")

        sm.add_widget(self.dashboard_screen)
        sm.add_widget(self.signals_screen)
        sm.add_widget(self.portfolio_screen)
        sm.add_widget(self.settings_screen)
        sm.add_widget(self.backtest_screen)

        # Synchroniser les signaux entre écrans
        Clock.schedule_interval(self._sync_screens, 35)

        return sm

    def _sync_screens(self, dt):
        """Propage les prix/signaux du dashboard vers les autres écrans et l'auto-trader."""
        prices  = self.dashboard_screen.get_prices()
        signals = self.dashboard_screen.get_signals()

        if hasattr(self.signals_screen, "refresh"):
            self.signals_screen.refresh(signals)
        if hasattr(self.portfolio_screen, "refresh"):
            self.portfolio_screen.refresh(prices)

        # Injecter les données dans le moteur de trading autonome
        get_auto_trader().update_market_data(prices, signals)

    def open_trade_dialog(self, signal_obj):
        """Ouvre le dialogue de confirmation de trade."""
        dialog = TradeDialog(signal_obj)
        dialog.open()


if __name__ == "__main__":
    MstreamTraderApp().run()
