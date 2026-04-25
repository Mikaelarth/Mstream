"""
Tests pytest : checkpoint (snapshot + auto-recovery du bot).

Vérifie :
  - Init de la table (idempotent)
  - save_snapshot crée une ligne, retourne id, purge anciens
  - load_latest_snapshot récupère le dernier
  - capture_current_state sérialise l'état des singletons
  - restore_state remet les valeurs dans les singletons
  - auto_recover_on_startup : True si snapshot < 24h, False sinon
"""

import pytest
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.adaptive as ad_mod
import core.circuit_breaker as cb_mod
import core.auto_trader as at_mod
from core import database, checkpoint
from core.checkpoint import (
    BotSnapshot, init_checkpoint_table,
    save_snapshot, load_latest_snapshot,
    capture_current_state, restore_state, auto_recover_on_startup,
)


@pytest.fixture(autouse=True)
def clean_checkpoint():
    """Reset DB + singletons + table checkpoints."""
    ad_mod._instance = None
    cb_mod._instance = None
    at_mod._instance = None
    database.init_db()
    init_checkpoint_table()
    with database.get_connection() as conn:
        conn.execute("DELETE FROM bot_checkpoints")
    yield
    with database.get_connection() as conn:
        conn.execute("DELETE FROM bot_checkpoints")


# ─── Save / Load ──────────────────────────────────────────────────────────────

def test_save_snapshot_returns_id():
    snap = BotSnapshot(circuit_state="warning", consecutive_sl=2)
    new_id = save_snapshot(snap)
    assert new_id > 0


def test_load_latest_snapshot_returns_none_when_empty():
    assert load_latest_snapshot() is None


def test_save_then_load_roundtrip():
    snap = BotSnapshot(
        circuit_state="triggered", consecutive_sl=5, sl_today=3,
        peak_capital=1500.0, current_regime="bull",
        regime_deviation_pct=4.5,
    )
    save_snapshot(snap)
    loaded = load_latest_snapshot()
    assert loaded is not None
    assert loaded.circuit_state == "triggered"
    assert loaded.consecutive_sl == 5
    assert loaded.sl_today == 3
    assert loaded.peak_capital == 1500.0
    assert loaded.current_regime == "bull"
    assert loaded.regime_deviation_pct == pytest.approx(4.5)


def test_load_returns_most_recent():
    """Plusieurs snapshots → load retourne le dernier."""
    save_snapshot(BotSnapshot(circuit_state="healthy"))
    time.sleep(0.01)   # garantir des timestamps distincts
    save_snapshot(BotSnapshot(circuit_state="warning"))
    time.sleep(0.01)
    save_snapshot(BotSnapshot(circuit_state="frozen"))
    loaded = load_latest_snapshot()
    assert loaded.circuit_state == "frozen"


def test_purge_keeps_only_n_recent():
    """save avec keep_last_n=3 → table contient max 3 lignes."""
    for i in range(10):
        save_snapshot(BotSnapshot(consecutive_sl=i), keep_last_n=3)
        time.sleep(0.01)
    with database.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM bot_checkpoints").fetchone()[0]
    assert count == 3


def test_load_handles_corrupt_json(monkeypatch):
    """Si la ligne en DB contient du JSON invalide → None sans crash."""
    with database.get_connection() as conn:
        conn.execute(
            "INSERT INTO bot_checkpoints (snapshot_json, created_at) VALUES (?, ?)",
            ("not valid json {{{", "2026-01-01T00:00:00")
        )
    result = load_latest_snapshot()
    assert result is None


def test_load_filters_unknown_fields():
    """JSON contient des champs hors dataclass → ils sont ignorés."""
    import json as json_mod
    with database.get_connection() as conn:
        conn.execute(
            "INSERT INTO bot_checkpoints (snapshot_json, created_at) VALUES (?, ?)",
            (json_mod.dumps({
                "circuit_state": "warning",
                "consecutive_sl": 3,
                "extra_unknown_field": "should be ignored",
            }), "2026-01-01T00:00:00")
        )
    snap = load_latest_snapshot()
    assert snap is not None
    assert snap.circuit_state == "warning"
    assert snap.consecutive_sl == 3


# ─── capture / restore ────────────────────────────────────────────────────────

def test_capture_current_state_returns_snapshot():
    snap = capture_current_state()
    assert isinstance(snap, BotSnapshot)
    # Au moins le timestamp doit être proche de maintenant
    assert abs(snap.timestamp - time.time()) < 5.0


def test_restore_state_updates_circuit_breaker():
    """Restorer un snapshot → les valeurs sont visibles dans CB."""
    cb = cb_mod.get_circuit_breaker()
    snap = BotSnapshot(
        circuit_state="warning", consecutive_sl=4, sl_today=2,
        peak_capital=2000.0, consecutive_api_errors=1,
    )
    ok = restore_state(snap)
    assert ok is True
    cb_state = cb.get_state_snapshot()
    assert cb_state["state"] == "warning"
    assert cb_state["consecutive_sl"] == 4
    assert cb_state["sl_today"] == 2
    assert cb_state["peak_capital"] == 2000.0


# ─── Auto-recovery ────────────────────────────────────────────────────────────

def test_auto_recover_no_snapshot():
    """Aucun snapshot en DB → False (start clean)."""
    assert auto_recover_on_startup() is False


def test_auto_recover_recent_snapshot():
    """Snapshot récent → True (restauration)."""
    snap = BotSnapshot(
        circuit_state="warning", consecutive_sl=3,
        timestamp=time.time(),   # maintenant
    )
    save_snapshot(snap)
    result = auto_recover_on_startup()
    assert result is True


def test_auto_recover_skips_old_snapshot():
    """Snapshot > 24h → False (on repart de zéro pour éviter état stale)."""
    snap = BotSnapshot(
        circuit_state="frozen",
        timestamp=time.time() - 100000,   # 27h
    )
    save_snapshot(snap)
    result = auto_recover_on_startup()
    assert result is False
