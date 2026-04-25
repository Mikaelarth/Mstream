"""
Tests d'intégration : AutoTrader (Bot Maître).

Le _cycle() est le tronc commun du bot — un bug ici casse tout.
On vérifie sans lancer le thread :
  - Cycle de vie : init, état initial, update_market_data thread-safe
  - _cycle() avec données vides → return early sans crash
  - _cycle() avec master inactif → ne fait rien sur master_*
  - _cycle() avec master actif + budget = 0 → status d'avertissement
  - _check_drawdown(): True si capital < threshold
  - Paper mode resolution : portfolio_type, budget_key, initial_key
  - _compute_roi : cohérent avec les settings
  - get_status / is_running : reflètent l'état réel
"""

import pytest
import sys
import os
import time
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.adaptive as ad_mod
import core.circuit_breaker as cb_mod
from core import database, paper_mode, auto_trader as at_mod
from core.auto_trader import AutoTrader, MASTER_CONFIG


@pytest.fixture(autouse=True)
def clean_state():
    """Reset singletons + paper mode + DB avant chaque test."""
    ad_mod._instance = None
    cb_mod._instance = None
    at_mod._instance = None
    database.init_db()
    paper_mode.set_paper_mode(False)
    # Reset settings critiques
    database.set_setting("auto_trade_master", "false")
    database.set_setting("auto_trade_securite", "false")
    database.set_setting("auto_trade_libre", "false")
    database.set_setting("budget_master", "0")
    database.set_setting("budget_master_initial", "0")
    database.set_setting("budget_master_paper", "0")
    database.set_setting("budget_master_initial_paper", "0")
    yield
    paper_mode.set_paper_mode(False)
    at_mod._instance = None


# ─── Initialisation ───────────────────────────────────────────────────────────

def test_autotrader_initial_state():
    bot = AutoTrader()
    assert bot.is_running is False
    assert "attente" in bot.get_status().lower()
    assert bot._cycle_count == 0
    assert bot._latest_signals == []
    assert bot._latest_prices == {}


def test_autotrader_singleton():
    """get_auto_trader() retourne toujours la même instance."""
    a = at_mod.get_auto_trader()
    b = at_mod.get_auto_trader()
    assert a is b


# ─── Injection de données thread-safe ─────────────────────────────────────────

def test_update_market_data_stores_state():
    bot = AutoTrader()
    bot.update_market_data({"btc": {"price": 50000}}, ["sig1", "sig2"])
    with bot._lock:
        assert bot._latest_prices == {"btc": {"price": 50000}}
        assert bot._latest_signals == ["sig1", "sig2"]
        assert bot._data_timestamp > 0


def test_update_market_data_concurrent_safe():
    """100 updates depuis 5 threads → pas de corruption d'état."""
    bot = AutoTrader()
    errors = []

    def writer(idx):
        try:
            for i in range(100):
                bot.update_market_data({f"c{idx}": i}, [idx, i])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert errors == []
    # L'état final doit être cohérent (un des derniers writes)
    with bot._lock:
        assert isinstance(bot._latest_prices, dict)
        assert isinstance(bot._latest_signals, list)


# ─── Paper mode resolution ────────────────────────────────────────────────────

def test_resolved_keys_real_mode():
    bot = AutoTrader()
    paper_mode.set_paper_mode(False)
    assert bot._resolved_portfolio_type() == "master"
    assert bot._resolved_budget_key() == "budget_master"
    assert bot._resolved_initial_key() == "budget_master_initial"


def test_resolved_keys_paper_mode():
    bot = AutoTrader()
    paper_mode.set_paper_mode(True)
    assert bot._resolved_portfolio_type() == "master_paper"
    assert bot._resolved_budget_key() == "budget_master_paper"
    # Convention : suffixe _paper appliqué à la clé originale
    assert bot._resolved_initial_key() == "budget_master_initial_paper"


# ─── _cycle() comportement ────────────────────────────────────────────────────

def test_cycle_no_data_returns_early(monkeypatch):
    """Pas de données injectées + fetch retourne vide → status d'attente."""
    bot = AutoTrader()
    # Bloquer le fetch autonome pour ne pas faire de HTTP
    monkeypatch.setattr(bot, "_fetch_own_data", lambda: ({}, []))
    bot._cycle()
    assert "attente" in bot._status.lower() or "données" in bot._status.lower()


def test_cycle_increments_count(monkeypatch):
    """Chaque _cycle() incrémente le compteur (utilisé pour planning checkpoint)."""
    bot = AutoTrader()
    monkeypatch.setattr(bot, "_fetch_own_data", lambda: ({}, []))
    initial = bot._cycle_count
    bot._cycle()
    bot._cycle()
    bot._cycle()
    assert bot._cycle_count == initial + 3


def test_cycle_master_inactive_no_master_logic(monkeypatch):
    """Si auto_trade_master=false, on ne lance pas _run_master_cycle."""
    bot = AutoTrader()
    database.set_setting("auto_trade_master", "false")
    bot.update_market_data({"bitcoin": {"price": 50000}}, [object()])

    called = {"flag": False}
    monkeypatch.setattr(bot, "_run_master_cycle",
                          lambda *a, **kw: called.update(flag=True))
    monkeypatch.setattr(bot, "_run_periodic_tasks", lambda *a, **kw: None)
    bot._cycle()
    assert called["flag"] is False


def test_cycle_master_active_zero_budget_warns(monkeypatch):
    """Master actif mais budget=0 → status warning, pas de cycle master."""
    bot = AutoTrader()
    database.set_setting("auto_trade_master", "true")
    database.set_setting("budget_master", "0")
    bot.update_market_data({"bitcoin": {"price": 50000}}, [object()])

    called = {"flag": False}
    monkeypatch.setattr(bot, "_run_master_cycle",
                          lambda *a, **kw: called.update(flag=True))
    monkeypatch.setattr(bot, "_run_periodic_tasks", lambda *a, **kw: None)
    bot._cycle()
    assert called["flag"] is False
    assert "budget" in bot._status.lower()


def test_cycle_master_active_with_budget_calls_master_cycle(monkeypatch):
    """Master actif + budget > 0 + drawdown OK → _run_master_cycle est appelé."""
    bot = AutoTrader()
    database.set_setting("auto_trade_master", "true")
    database.set_setting("budget_master", "1000")
    database.set_setting("budget_master_initial", "1000")
    bot.update_market_data({"bitcoin": {"price": 50000}}, [object()])

    called = {"flag": False, "budget": None}

    def spy(prices, signals, budget):
        called["flag"] = True
        called["budget"] = budget

    monkeypatch.setattr(bot, "_run_master_cycle", spy)
    monkeypatch.setattr(bot, "_run_periodic_tasks", lambda *a, **kw: None)
    bot._cycle()
    assert called["flag"] is True
    assert called["budget"] == 1000.0


def test_cycle_resets_ohlcv_cache_each_iteration(monkeypatch):
    """Le cache OHLCV per-cycle doit être vidé au début de chaque _cycle()."""
    bot = AutoTrader()
    monkeypatch.setattr(bot, "_fetch_own_data", lambda: ({}, []))
    bot._cycle_ohlcv_cache = {"poison": "data"}
    bot._cycle()
    assert bot._cycle_ohlcv_cache == {}


# ─── Drawdown ─────────────────────────────────────────────────────────────────

def test_check_drawdown_under_threshold():
    """Capital baisse à 81% (DD = 19%, < 20% seuil) → False (pas de pause)."""
    bot = AutoTrader()
    database.set_setting("budget_master_initial", "1000")
    paper_mode.set_paper_mode(False)
    assert bot._check_drawdown(810) is False


def test_check_drawdown_over_threshold():
    """Capital baisse à 79% (DD = 21%, > 20% seuil) → True (pause)."""
    bot = AutoTrader()
    database.set_setting("budget_master_initial", "1000")
    paper_mode.set_paper_mode(False)
    assert bot._check_drawdown(790) is True


def test_check_drawdown_no_initial_returns_false():
    """Sans budget_master_initial → on ne peut pas calculer → False (safe)."""
    bot = AutoTrader()
    database.set_setting("budget_master_initial", "0")
    paper_mode.set_paper_mode(False)
    assert bot._check_drawdown(500) is False


# ─── ROI ──────────────────────────────────────────────────────────────────────

def test_compute_roi_zero_when_no_initial():
    bot = AutoTrader()
    database.set_setting("budget_master_initial", "0")
    database.set_setting("budget_master", "1000")
    paper_mode.set_paper_mode(False)
    assert bot._compute_roi() == 0.0


def test_compute_roi_positive_growth():
    bot = AutoTrader()
    database.set_setting("budget_master_initial", "1000")
    database.set_setting("budget_master", "1500")
    paper_mode.set_paper_mode(False)
    assert bot._compute_roi() == pytest.approx(50.0)


def test_compute_roi_loss():
    bot = AutoTrader()
    database.set_setting("budget_master_initial", "1000")
    database.set_setting("budget_master", "750")
    paper_mode.set_paper_mode(False)
    assert bot._compute_roi() == pytest.approx(-25.0)


# ─── Régime cache ─────────────────────────────────────────────────────────────

def test_get_regime_returns_neutral_initially():
    bot = AutoTrader()
    regime, dev = bot.get_regime()
    # Initial state = NEUTRAL avec deviation None
    assert regime.value == "neutral"
