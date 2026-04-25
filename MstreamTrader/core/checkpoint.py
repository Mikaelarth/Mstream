"""
MstreamTrader - Checkpointing & Recovery
==========================================

Snapshot périodique de l'état du bot pour pouvoir reprendre proprement
après un crash, un kill, ou un redémarrage de l'appareil.

Les positions ouvertes sont déjà persistées en DB via open_positions.
Ce module capture les états VOLATILES (en mémoire uniquement) :
    - Circuit breaker state (niveau actuel, compteurs)
    - Régime courant détecté et son timestamp
    - Health checker derniers résultats
    - Timestamp du dernier cycle complet
    - Peak capital (pour le drawdown)

Snapshots écrits dans une table dédiée `bot_checkpoints`, purge automatique
des anciens pour garder N dernières entrées seulement.
"""

import json
import time
from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class BotSnapshot:
    """État volatile du bot à un instant T."""
    timestamp:               float = field(default_factory=time.time)

    # Circuit breaker
    circuit_state:           str   = "healthy"
    consecutive_sl:          int   = 0
    sl_today:                int   = 0
    peak_capital:            float = 0.0
    consecutive_api_errors:  int   = 0

    # Régime
    current_regime:          str   = "neutral"
    regime_deviation_pct:    Optional[float] = None
    regime_ts:               float = 0.0

    # Cycle
    last_cycle_ts:           float = 0.0
    last_cycle_id:           str   = ""

    # Stats récentes (pour recovery des KPIs)
    trades_last_24h:         int   = 0
    pnl_last_24h:            float = 0.0


def init_checkpoint_table():
    """Crée la table bot_checkpoints si elle n'existe pas."""
    from core.database import get_connection
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bot_checkpoints (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_json  TEXT NOT NULL,
                created_at     TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_checkpoint_created
                ON bot_checkpoints(created_at DESC);
        """)


def save_snapshot(snap: BotSnapshot, keep_last_n: int = 20) -> int:
    """
    Sauvegarde un snapshot et purge les plus anciens au-delà de N.
    Retourne l'id du snapshot créé.
    """
    from datetime import datetime
    from core.database import get_connection

    try:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO bot_checkpoints (snapshot_json, created_at) VALUES (?, ?)",
                (json.dumps(asdict(snap), default=str, ensure_ascii=False),
                 datetime.now().isoformat())
            )
            new_id = cur.lastrowid

            # Purge : garder N derniers
            conn.execute(
                """DELETE FROM bot_checkpoints
                   WHERE id NOT IN (
                       SELECT id FROM bot_checkpoints
                       ORDER BY created_at DESC LIMIT ?)""",
                (keep_last_n,)
            )
            return new_id or 0
    except Exception as exc:
        import logging
        logging.getLogger("checkpoint").warning(f"Echec save snapshot : {exc}")
        return 0


def load_latest_snapshot() -> Optional[BotSnapshot]:
    """Charge le snapshot le plus récent, None si aucun."""
    from core.database import get_connection
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT snapshot_json FROM bot_checkpoints "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            data = json.loads(row["snapshot_json"])
            return BotSnapshot(**{k: v for k, v in data.items()
                                  if k in BotSnapshot.__dataclass_fields__})
    except (ValueError, KeyError, TypeError) as exc:
        import logging
        logging.getLogger("checkpoint").warning(f"load_latest_snapshot failed: {exc}")
        return None


def capture_current_state() -> BotSnapshot:
    """Capture l'état courant du bot à partir des singletons."""
    snap = BotSnapshot()

    # Circuit breaker — snapshot atomique (évite les accès self.state.X sans lock)
    try:
        from core.circuit_breaker import get_circuit_breaker
        cb_snap = get_circuit_breaker().get_state_snapshot()
        snap.circuit_state           = cb_snap["state"]
        snap.consecutive_sl          = cb_snap["consecutive_sl"]
        snap.sl_today                = cb_snap["sl_today"]
        snap.peak_capital            = cb_snap["peak_capital"]
        snap.consecutive_api_errors  = cb_snap["consecutive_api_errors"]
    except (ImportError, KeyError, AttributeError) as exc:
        import logging
        logging.getLogger("checkpoint").warning(f"CB capture failed: {exc}")

    # Régime depuis le bot (getter public qui retourne un tuple)
    try:
        from core.auto_trader import get_auto_trader
        bot = get_auto_trader()
        regime, dev = bot.get_regime()
        snap.current_regime       = regime.value
        snap.regime_deviation_pct = dev
        snap.regime_ts            = bot._regime_ts
    except (ImportError, AttributeError) as exc:
        import logging
        logging.getLogger("checkpoint").warning(f"Bot capture failed: {exc}")

    return snap


def restore_state(snap: BotSnapshot) -> bool:
    """
    Restaure l'état volatile dans les singletons.
    Retourne True si la restauration a réussi.
    """
    ok = True

    try:
        from core.circuit_breaker import get_circuit_breaker, CircuitState
        cb = get_circuit_breaker()
        with cb._lock:
            cb.state.state = CircuitState(snap.circuit_state)
            cb.state.consecutive_sl = snap.consecutive_sl
            cb.state.sl_today       = snap.sl_today
            cb.state.peak_capital   = snap.peak_capital
            cb.state.consecutive_api_errors = snap.consecutive_api_errors
    except Exception as exc:
        import logging
        logging.getLogger("checkpoint").warning(f"Echec restore circuit : {exc}")
        ok = False

    try:
        from core.auto_trader import get_auto_trader
        from core.regime import Regime
        bot = get_auto_trader()
        bot._regime           = Regime(snap.current_regime)
        bot._regime_deviation = snap.regime_deviation_pct
        bot._regime_ts        = snap.regime_ts
    except Exception as exc:
        import logging
        logging.getLogger("checkpoint").warning(f"Echec restore regime : {exc}")
        ok = False

    return ok


def auto_recover_on_startup() -> bool:
    """
    Appelé au démarrage du bot : charge et restaure le snapshot le plus récent.
    Retourne True si un snapshot a été restauré, False sinon.
    """
    init_checkpoint_table()
    snap = load_latest_snapshot()
    if snap is None:
        return False

    age_sec = time.time() - snap.timestamp
    if age_sec > 86400:   # > 24h = on repart de zéro
        return False

    return restore_state(snap)
