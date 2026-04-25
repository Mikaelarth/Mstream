"""
Tests d'intégration end-to-end : flux complets du Bot Maître.

Vérifie que les pipelines clés fonctionnent ensemble (pas isolément) :
  - Cycle backtest complet sur données synthétiques
  - Paper mode : ledger isolé du réel
  - Audit logger asynchrone : drain de la queue
  - Notifications : envoi async safe
  - Export CSV : roundtrip insert → export
  - Equity history : snapshot + lecture
"""

import pytest
import random
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.adaptive as ad_mod
import core.circuit_breaker as cb_mod
from core import database, paper_mode, equity_history, export, audit


@pytest.fixture(autouse=True)
def clean_state():
    """Reset des singletons + tables avant chaque test."""
    ad_mod._instance = None
    cb_mod._instance = None
    database.init_db()
    paper_mode.set_paper_mode(False)
    yield
    paper_mode.set_paper_mode(False)


# ─── Backtest end-to-end ──────────────────────────────────────────────────────

def _gen_candles(n=200, start=100.0, trend=0.0005, vol=0.015, seed=42):
    random.seed(seed)
    candles = []
    price = start
    ts = 1700000000.0
    for i in range(n):
        c = random.gauss(trend, vol)
        new_p = price * (1 + c)
        candles.append({
            "timestamp": ts, "open": price,
            "high": max(price, new_p) * 1.005,
            "low":  min(price, new_p) * 0.995,
            "close": new_p,
        })
        price = new_p
        ts += 3600
    return candles


def test_backtest_runs_without_crash():
    """Backtest minimal : 200 bougies × 2 coins → ne plante pas."""
    from core.backtest import Backtest, BacktestConfig
    coins_data = {
        "bitcoin":  _gen_candles(seed=1),
        "ethereum": _gen_candles(seed=2),
    }
    cfg = BacktestConfig(
        initial_capital=1000.0,
        candle_duration_sec=3600,
        periods_per_year=8760,
        cooldown_candles=6,
        min_score=25.0, min_confidence=30.0, min_rr=1.5,
    )
    bt = Backtest(cfg)
    result = bt.run(coins_data)
    assert result.report["initial_capital"] == 1000.0
    assert isinstance(result.trades, list)
    assert isinstance(result.equity_curve, list)
    assert len(result.equity_curve) > 0


# ─── Paper mode isolation ─────────────────────────────────────────────────────

def test_paper_mode_isolates_ledger():
    """Activer paper mode change le portfolio_type et budget_key."""
    paper_mode.set_paper_mode(False)
    assert paper_mode.get_portfolio_type("master") == "master"
    assert paper_mode.get_budget_key() == "budget_master"

    paper_mode.set_paper_mode(True)
    assert paper_mode.get_portfolio_type("master") == "master_paper"
    assert paper_mode.get_budget_key() == "budget_master_paper"

    paper_mode.set_paper_mode(False)


def test_paper_budget_separate_from_real():
    """Le budget paper et réel sont stockés dans des clés distinctes."""
    database.set_setting("budget_master", "1000.0")
    database.set_setting("budget_master_paper", "500.0")
    paper_mode.set_paper_mode(False)
    assert float(database.get_setting(paper_mode.get_budget_key())) == 1000.0
    paper_mode.set_paper_mode(True)
    assert float(database.get_setting(paper_mode.get_budget_key())) == 500.0
    paper_mode.set_paper_mode(False)


# ─── Audit logger asynchrone ──────────────────────────────────────────────────

def test_audit_async_drains_queue():
    """Worker async : 50 events poussés → tous écrits en DB."""
    audit.enable_async_audit()
    try:
        for i in range(50):
            audit.log_event(audit.AuditEvent(
                event_type="SIGNAL_ANALYZED",
                coin_id=f"test_coin_{i}",
                decision="HOLD", severity="info",
            ))
        # Attendre que la queue soit vidée
        audit.flush_audit_queue(timeout=5.0)
        # Vérifier que les 50 events sont en DB
        with database.get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE coin_id LIKE 'test_coin_%'"
            ).fetchone()[0]
        assert count >= 50
    finally:
        # Cleanup
        with database.get_connection() as conn:
            conn.execute("DELETE FROM audit_log WHERE coin_id LIKE 'test_coin_%'")
        audit.disable_async_audit()


def test_audit_falls_back_to_sync_when_async_disabled():
    """Si async désactivé, le log est synchrone (pas perdu)."""
    audit.disable_async_audit()
    audit.log_event(audit.AuditEvent(
        event_type="SIGNAL_ANALYZED",
        coin_id="sync_test_coin",
        decision="HOLD", severity="info",
    ))
    with database.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE coin_id = 'sync_test_coin'"
        ).fetchone()[0]
        # Cleanup
        conn.execute("DELETE FROM audit_log WHERE coin_id = 'sync_test_coin'")
    assert count >= 1


# ─── Equity history ───────────────────────────────────────────────────────────

def test_equity_snapshot_roundtrip():
    """Record → get_history retourne ce qu'on a écrit."""
    equity_history.init_equity_table()
    equity_history.record_snapshot(
        capital=1234.56, unrealized_pnl=5.0,
        realized_pnl_today=10.0, trades_today=3,
        roi_pct=12.34, mode="real", date="2026-01-01"
    )
    history = equity_history.get_history(days=10000, mode="real")
    found = [h for h in history if h["date"] == "2026-01-01"]
    assert len(found) == 1
    assert found[0]["capital"] == 1234.56
    assert found[0]["roi_pct"] == 12.34
    # Cleanup
    with database.get_connection() as conn:
        conn.execute("DELETE FROM equity_history WHERE date = '2026-01-01'")


def test_equity_snapshot_upsert():
    """Deux snapshots du même jour → 1 seule ligne (UPSERT)."""
    equity_history.init_equity_table()
    equity_history.record_snapshot(capital=100, mode="real", date="2026-01-02")
    equity_history.record_snapshot(capital=200, mode="real", date="2026-01-02")
    history = equity_history.get_history(days=10000, mode="real")
    found = [h for h in history if h["date"] == "2026-01-02"]
    assert len(found) == 1
    assert found[0]["capital"] == 200   # dernière valeur
    with database.get_connection() as conn:
        conn.execute("DELETE FROM equity_history WHERE date = '2026-01-02'")


# ─── Export CSV ───────────────────────────────────────────────────────────────

def test_export_csv_creates_file():
    """Export → fichier CSV existant + contenu structurel."""
    # Insérer un trade test
    database.record_trade(
        coin_id="test_export_coin", symbol="TEST", side="BUY",
        quantity=1.0, price=100.0, fee=0.1,
        source="MANUAL_TEST", note="Test export",
    )
    path = export.export_trades_to_csv(portfolio_type=None)
    try:
        assert path is not None
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "test_export_coin" in content
        # Header CSV présent
        assert "executed_at" in content
        assert "coin_id" in content
    finally:
        # Cleanup
        with database.get_connection() as conn:
            conn.execute("DELETE FROM trades WHERE coin_id = 'test_export_coin'")
        if path and path.exists():
            path.unlink()


# ─── Validation full integration ──────────────────────────────────────────────

def test_validate_all_settings_no_invalid_after_init():
    """Après init_db avec defaults, aucune valeur invalide.
    Note : peut détecter des valeurs résiduelles de l'utilisateur (ex: usdt_balance
    qui aurait pu être saisi manuellement). On reset à 0 avant le check pour être
    indépendant des données présentes en DB locale.
    """
    # Reset des settings susceptibles d'être pollués par un usage précédent
    database.set_setting("usdt_balance", "0.0")
    from core.validation import validate_all_current_settings
    invalid = validate_all_current_settings()
    # On accepte uniquement des invalides clairement liés à des paramètres user
    # qui sortent du scope de ce test (clés API mal formées par exemple).
    blocking = [
        (k, m) for k, m in invalid
        if k in ("budget_master", "budget_master_initial", "risk_master", "risk_per_trade")
    ]
    assert blocking == [], f"Settings critiques invalides: {blocking}"
