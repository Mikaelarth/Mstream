"""
Tests pytest : module audit (mode sync, mode async, queue, query, purge).

Vérifie :
  - Mode sync : log_event écrit immédiatement
  - Mode async : worker drain la queue
  - enable_async_audit idempotent (re-call sans crash)
  - disable_async_audit join propre
  - Queue saturée → fallback sync (pas perdu)
  - Helpers (log_signal_analyzed, log_entry, etc.) écrivent bons event_type
  - cycle_id permet de regrouper events
  - query_events filtres OK + JSON parse robuste
  - purge_old_events supprime correctement
  - Mode async puis disable → flush la queue avant join
"""

import pytest
import sys
import os
import time
import queue as queue_mod
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audit, database


def _clean_audit_rows():
    with database.get_connection() as conn:
        conn.execute(
            "DELETE FROM audit_log "
            "WHERE coin_id LIKE 'AUDIT_TEST_%' OR cycle_id LIKE 'AUDIT_TEST_%'"
        )


@pytest.fixture(autouse=True)
def clean_audit():
    """Reset DB + clean audit table avant/après chaque test."""
    database.init_db()
    audit.disable_async_audit()
    _clean_audit_rows()
    yield
    audit.disable_async_audit()
    _clean_audit_rows()


# ─── Mode sync ────────────────────────────────────────────────────────────────

def test_log_event_sync_writes_to_db():
    audit.log_event(audit.AuditEvent(
        event_type="SIGNAL_ANALYZED",
        coin_id="AUDIT_TEST_sync_1",
        decision="HOLD",
    ))
    events = audit.query_events(coin_id="AUDIT_TEST_sync_1")
    assert len(events) == 1
    assert events[0]["event_type"] == "SIGNAL_ANALYZED"
    assert events[0]["decision"] == "HOLD"


def test_log_event_persists_inputs_outputs_as_json():
    audit.log_event(audit.AuditEvent(
        event_type="KELLY_SIZING",
        coin_id="AUDIT_TEST_json",
        inputs={"win_rate": 0.6, "avg_win": 1.5},
        outputs={"size_usdt": 100.0},
        reasoning=["raison 1", "raison 2"],
    ))
    events = audit.query_events(coin_id="AUDIT_TEST_json")
    assert len(events) == 1
    assert events[0]["inputs"]["win_rate"] == 0.6
    assert events[0]["outputs"]["size_usdt"] == 100.0
    assert events[0]["reasoning"] == ["raison 1", "raison 2"]


# ─── Mode async ───────────────────────────────────────────────────────────────

def test_async_drains_queue():
    audit.enable_async_audit()
    for i in range(20):
        audit.log_event(audit.AuditEvent(
            event_type="SIGNAL_ANALYZED",
            coin_id=f"AUDIT_TEST_async_{i}",
        ))
    audit.flush_audit_queue(timeout=5.0)
    with database.get_connection() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE coin_id LIKE 'AUDIT_TEST_async_%'"
        ).fetchone()[0]
    assert n == 20


def test_enable_async_idempotent():
    """Appeler enable 2× ne doit pas créer 2 threads."""
    audit.enable_async_audit()
    t1 = audit._audit_worker_thread
    audit.enable_async_audit()
    t2 = audit._audit_worker_thread
    assert t1 is t2 and t1.is_alive()


def test_disable_async_joins_thread():
    audit.enable_async_audit()
    t = audit._audit_worker_thread
    assert t.is_alive()
    audit.disable_async_audit(timeout=2.0)
    # Laisser le temps au thread de sortir de sa boucle (timeout interne 0.5s)
    t.join(timeout=2.0)
    assert not t.is_alive()


def test_async_full_queue_falls_back_sync(monkeypatch):
    """Si la queue est pleine, l'event est écrit sync (pas perdu)."""
    audit.enable_async_audit()

    # Simuler queue pleine en patchant put_nowait
    def raise_full(item, *a, **kw):
        raise queue_mod.Full()

    monkeypatch.setattr(audit._audit_queue, "put_nowait", raise_full)

    audit.log_event(audit.AuditEvent(
        event_type="SIGNAL_ANALYZED",
        coin_id="AUDIT_TEST_overflow",
    ))
    # Le fallback sync écrit directement → check immédiat
    events = audit.query_events(coin_id="AUDIT_TEST_overflow")
    assert len(events) == 1


# ─── Helpers spécialisés ──────────────────────────────────────────────────────

class _FakeSignal:
    """Stub minimal pour log_signal_analyzed."""
    def __init__(self):
        self.signal = type("S", (), {"value": "BUY"})()
        self.score = 75.0
        self.confidence = 80.0
        self.risk_reward = 2.5
        self.price = 50000.0
        self.stop_loss = 49000.0
        self.take_profit = 53000.0
        self.reasons = ["RSI bull", "MACD cross"]


def test_log_signal_analyzed_writes_correct_type():
    sig = _FakeSignal()
    audit.log_signal_analyzed("AUDIT_TEST_btc", "BTC", sig, cycle_id="AUDIT_TEST_cyc_1")
    events = audit.query_events(cycle_id="AUDIT_TEST_cyc_1")
    assert len(events) == 1
    assert events[0]["event_type"] == "SIGNAL_ANALYZED"
    assert events[0]["outputs"]["score"] == 75.0


def test_log_entry_executed_records_risk():
    audit.log_entry_executed(
        coin_id="AUDIT_TEST_eth", symbol="ETH",
        price=2000.0, quantity=0.5, amount_usdt=1000.0,
        sl=1900.0, tp=2200.0, sizing_info={"kelly": 0.05},
        cycle_id="AUDIT_TEST_cyc_2",
    )
    events = audit.query_events(cycle_id="AUDIT_TEST_cyc_2")
    assert len(events) == 1
    assert events[0]["event_type"] == "ENTRY_EXECUTED"
    assert events[0]["outputs"]["risk_usdt"] == pytest.approx(50.0)   # (2000-1900)*0.5


def test_log_position_closed_severity_on_loss():
    audit.log_position_closed(
        coin_id="AUDIT_TEST_loss", symbol="X",
        entry_price=100.0, exit_price=90.0,
        quantity=1.0, pnl=-10.0, reason="EXIT_SL",
    )
    events = audit.query_events(coin_id="AUDIT_TEST_loss")
    assert len(events) == 1
    assert events[0]["severity"] == "warning"


def test_log_regime_change_includes_metadata():
    audit.log_regime_change("bull", "bear", -8.5, cycle_id="AUDIT_TEST_cyc_regime")
    events = audit.query_events(cycle_id="AUDIT_TEST_cyc_regime")
    assert len(events) == 1
    assert events[0]["event_type"] == "REGIME_CHANGED"
    assert events[0]["outputs"]["new_regime"] == "bear"


# ─── cycle_id grouping ────────────────────────────────────────────────────────

def test_cycle_summary_groups_events():
    cyc_id = "AUDIT_TEST_cyc_summary"
    sig = _FakeSignal()
    audit.log_signal_analyzed("AUDIT_TEST_a", "A", sig, cycle_id=cyc_id)
    audit.log_entry_executed("AUDIT_TEST_a", "A", 100, 1, 100, 95, 110,
                              cycle_id=cyc_id)
    audit.log_position_closed("AUDIT_TEST_a", "A", 100, 110, 1, 10,
                                "EXIT_TP", cycle_id=cyc_id)
    summary = audit.cycle_summary(cyc_id)
    assert summary["event_count"] == 3
    assert summary["entries"] == 1
    assert summary["exits"] == 1
    assert summary["signals_analyzed"] == 1


# ─── Query filters ────────────────────────────────────────────────────────────

def test_query_events_filter_by_event_type():
    sig = _FakeSignal()
    audit.log_signal_analyzed("AUDIT_TEST_q1", "X", sig)
    audit.log_entry_executed("AUDIT_TEST_q1", "X", 1, 1, 1, 0.5, 1.5)
    res_signals = audit.query_events(
        event_type="SIGNAL_ANALYZED", coin_id="AUDIT_TEST_q1"
    )
    res_entries = audit.query_events(
        event_type="ENTRY_EXECUTED", coin_id="AUDIT_TEST_q1"
    )
    assert len(res_signals) == 1
    assert len(res_entries) == 1


def test_query_respects_limit():
    for i in range(15):
        audit.log_event(audit.AuditEvent(
            event_type="SIGNAL_ANALYZED",
            coin_id=f"AUDIT_TEST_lim_{i}",
        ))
    res = audit.query_events(event_type="SIGNAL_ANALYZED", limit=5)
    # Le filtre ne porte pas sur coin_id : on vérifie juste le LIMIT
    assert len(res) <= 5


# ─── Purge ────────────────────────────────────────────────────────────────────

def test_purge_old_events_removes_old(monkeypatch):
    """Insère un event avec created_at très ancien, vérifie qu'il est purgé."""
    # Insertion directe avec date < cutoff
    with database.get_connection() as conn:
        conn.execute(
            """INSERT INTO audit_log
               (event_type, coin_id, symbol, decision, severity,
                inputs_json, outputs_json, reasoning, cycle_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SIGNAL_ANALYZED", "AUDIT_TEST_purge_old", "X", "HOLD", "info",
             "{}", "{}", "[]", None, "2020-01-01T00:00:00")
        )
        # + un event récent qui doit rester
    audit.log_event(audit.AuditEvent(
        event_type="SIGNAL_ANALYZED",
        coin_id="AUDIT_TEST_purge_recent",
    ))
    removed = audit.purge_old_events(days=30)
    assert removed >= 1
    # Le récent doit être encore là
    res = audit.query_events(coin_id="AUDIT_TEST_purge_recent")
    assert len(res) == 1
    # L'ancien doit avoir disparu
    res_old = audit.query_events(coin_id="AUDIT_TEST_purge_old")
    assert len(res_old) == 0
