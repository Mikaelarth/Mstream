"""
MstreamTrader - Audit Trail Structuré
========================================

Traçabilité institutionnelle de CHAQUE décision du bot.
Chaque événement est horodaté, typé, et accompagné du raisonnement complet
(inputs, scores, raisons, outputs) au format JSON dans la DB.

Objectif : pouvoir **reconstituer après coup** pourquoi le bot a pris
n'importe quelle décision, à des fins de debug, audit, compliance.

Types d'événements enregistrés :
    SIGNAL_ANALYZED    : signal calculé pour un coin (tous les scores)
    SIGNAL_QUALIFIED   : signal a passé tous les filtres
    SIGNAL_REJECTED    : signal rejeté, avec raison précise
    ENTRY_EXECUTED     : achat exécuté (prix réel, slippage mesuré)
    EXIT_TRIGGERED     : SL ou TP atteint
    POSITION_CLOSED    : position clôturée (P&L final)
    TRAILING_SL_UPDATE : stop-loss trailé
    REGIME_CHANGED     : bascule du régime de marché détectée
    CIRCUIT_BREAKER    : événement du circuit breaker
    CORRELATION_BLOCK  : entrée bloquée par la matrice de corrélation
    KELLY_SIZING       : calcul Kelly de taille de position
    CYCLE_COMPLETED    : cycle du bot terminé (résumé)
"""

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, asdict, field
from typing import Any, Optional


# ─── Worker async pour les inserts audit ──────────────────────────────────────
# Évite de bloquer le thread bot avec des INSERT SQL synchrones (15-25 / cycle).
# La queue fait tampon entre le bot (producteur) et un thread worker dédié
# (consommateur) qui écrit en DB.

_audit_queue: queue.Queue = queue.Queue(maxsize=1000)
_audit_worker_thread: Optional[threading.Thread] = None
_audit_worker_stop = threading.Event()
_audit_async_enabled = False


def _audit_worker_loop():
    """Boucle du thread worker : draine la queue et écrit en DB."""
    log = logging.getLogger("audit.worker")
    while not _audit_worker_stop.is_set():
        try:
            event = _audit_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _do_log_event_sync(event)
        except Exception as exc:
            log.warning(f"async log failed : {exc}")
        finally:
            _audit_queue.task_done()


def enable_async_audit():
    """Active le mode async : démarre le worker. Idempotent."""
    global _audit_worker_thread, _audit_async_enabled
    if _audit_worker_thread is not None and _audit_worker_thread.is_alive():
        return
    _audit_worker_stop.clear()
    _audit_worker_thread = threading.Thread(
        target=_audit_worker_loop, daemon=True, name="AuditWorker"
    )
    _audit_worker_thread.start()
    _audit_async_enabled = True
    logging.getLogger("audit").info("Audit logger asynchrone démarré")


def disable_async_audit(timeout: float = 2.0):
    """Arrête le worker (drain + stop). Pour tests / shutdown propre."""
    global _audit_async_enabled
    _audit_async_enabled = False
    _audit_worker_stop.set()
    if _audit_worker_thread is not None:
        _audit_worker_thread.join(timeout=timeout)


def flush_audit_queue(timeout: float = 5.0) -> bool:
    """Bloque jusqu'à drain de la queue (utile pour tests). Retourne True si vidée."""
    try:
        _audit_queue.join()
        return True
    except Exception:
        return False


AUDIT_EVENT_TYPES = [
    "SIGNAL_ANALYZED", "SIGNAL_QUALIFIED", "SIGNAL_REJECTED",
    "ENTRY_EXECUTED", "EXIT_TRIGGERED", "POSITION_CLOSED",
    "TRAILING_SL_UPDATE", "REGIME_CHANGED", "CIRCUIT_BREAKER",
    "CORRELATION_BLOCK", "KELLY_SIZING", "CYCLE_COMPLETED",
    "HEALTH_WARNING", "CONFIG_CHANGED", "API_CALL", "ERROR",
]


@dataclass
class AuditEvent:
    event_type:    str
    coin_id:       str = ""
    symbol:        str = ""
    decision:      str = ""         # "BUY" | "SELL" | "HOLD" | "SKIP" | ...
    severity:      str = "info"     # "info" | "warning" | "critical"
    inputs:        dict = field(default_factory=dict)     # données en entrée
    outputs:      dict = field(default_factory=dict)     # résultat de la décision
    reasoning:    list = field(default_factory=list)     # texte explicatif
    timestamp:    float = field(default_factory=time.time)
    cycle_id:     Optional[str] = None   # identifiant du cycle pour grouper


def init_audit_table():
    """Crée la table audit_log si elle n'existe pas."""
    from core.database import get_connection
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type   TEXT NOT NULL,
                coin_id      TEXT NOT NULL DEFAULT '',
                symbol       TEXT NOT NULL DEFAULT '',
                decision     TEXT NOT NULL DEFAULT '',
                severity     TEXT NOT NULL DEFAULT 'info',
                inputs_json  TEXT NOT NULL DEFAULT '{}',
                outputs_json TEXT NOT NULL DEFAULT '{}',
                reasoning    TEXT NOT NULL DEFAULT '',
                cycle_id     TEXT,
                created_at   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_type    ON audit_log(event_type);
            CREATE INDEX IF NOT EXISTS idx_audit_cycle   ON audit_log(cycle_id);
            CREATE INDEX IF NOT EXISTS idx_audit_coin    ON audit_log(coin_id);
        """)


def log_event(event: AuditEvent):
    """
    Enregistre un événement d'audit.
    - Mode async (recommandé) : push dans la queue, le worker écrit en DB
    - Mode sync (fallback) : INSERT direct (utilisé si worker pas actif)
    """
    if _audit_async_enabled:
        try:
            _audit_queue.put_nowait(event)
        except queue.Full:
            # Queue saturée (rarissime) → fallback sync pour ne pas perdre l'event
            _do_log_event_sync(event)
    else:
        _do_log_event_sync(event)


def _do_log_event_sync(event: AuditEvent):
    """Insert SQL synchrone (utilisé par le worker async ou en fallback)."""
    from datetime import datetime
    from core.database import get_connection
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO audit_log
                   (event_type, coin_id, symbol, decision, severity,
                    inputs_json, outputs_json, reasoning, cycle_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event.event_type, event.coin_id, event.symbol,
                 event.decision, event.severity,
                 json.dumps(event.inputs, default=str, ensure_ascii=False),
                 json.dumps(event.outputs, default=str, ensure_ascii=False),
                 json.dumps(event.reasoning, ensure_ascii=False),
                 event.cycle_id,
                 datetime.fromtimestamp(event.timestamp).isoformat())
            )
    except Exception as exc:
        # Un échec d'audit ne doit JAMAIS bloquer le bot
        logging.getLogger("audit").warning(f"Échec log audit : {exc}")


# ─── API publique : loggers spécialisés ──────────────────────────────────────

def log_signal_analyzed(coin_id: str, symbol: str, signal, cycle_id: str = None):
    """Log un signal calculé avec tous ses scores."""
    log_event(AuditEvent(
        event_type = "SIGNAL_ANALYZED",
        coin_id    = coin_id,
        symbol     = symbol,
        decision   = signal.signal.value if hasattr(signal.signal, "value") else str(signal.signal),
        severity   = "info",
        inputs     = {
            "price":       signal.price,
            "stop_loss":   signal.stop_loss,
            "take_profit": signal.take_profit,
            "risk_reward": signal.risk_reward,
        },
        outputs = {
            "score":       signal.score,
            "confidence":  signal.confidence,
        },
        reasoning = list(signal.reasons) if signal.reasons else [],
        cycle_id  = cycle_id,
    ))


def log_signal_qualified(coin_id: str, symbol: str, signal, cycle_id: str = None):
    """Log un signal qualifié (passé tous les filtres)."""
    log_event(AuditEvent(
        event_type = "SIGNAL_QUALIFIED",
        coin_id    = coin_id,
        symbol     = symbol,
        decision   = "QUALIFIED",
        severity   = "info",
        outputs    = {
            "score":       signal.score,
            "confidence":  signal.confidence,
            "risk_reward": signal.risk_reward,
        },
        cycle_id = cycle_id,
    ))


def log_signal_rejected(coin_id: str, symbol: str, signal, reason: str,
                         threshold: str = "", cycle_id: str = None):
    """Log un signal rejeté avec la raison précise."""
    log_event(AuditEvent(
        event_type = "SIGNAL_REJECTED",
        coin_id    = coin_id,
        symbol     = symbol,
        decision   = "SKIP",
        severity   = "info",
        inputs     = {
            "score":       signal.score,
            "confidence":  signal.confidence,
            "risk_reward": signal.risk_reward,
            "signal":      signal.signal.value if hasattr(signal.signal, "value") else str(signal.signal),
        },
        outputs   = {"threshold_violated": threshold},
        reasoning = [reason],
        cycle_id  = cycle_id,
    ))


def log_entry_executed(coin_id: str, symbol: str,
                        price: float, quantity: float, amount_usdt: float,
                        sl: float, tp: float, sizing_info: dict = None,
                        cycle_id: str = None):
    """Log une entrée exécutée avec les détails du sizing."""
    log_event(AuditEvent(
        event_type = "ENTRY_EXECUTED",
        coin_id    = coin_id,
        symbol     = symbol,
        decision   = "BUY",
        severity   = "info",
        inputs     = {
            "amount_usdt": amount_usdt,
            "sizing":      sizing_info or {},
        },
        outputs = {
            "executed_price": price,
            "quantity":       quantity,
            "stop_loss":      sl,
            "take_profit":    tp,
            "risk_usdt":      (price - sl) * quantity if price > sl else 0,
        },
        cycle_id = cycle_id,
    ))


def log_position_closed(coin_id: str, symbol: str, entry_price: float,
                         exit_price: float, quantity: float, pnl: float,
                         reason: str, cycle_id: str = None):
    """Log une position clôturée avec son P&L final."""
    pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
    log_event(AuditEvent(
        event_type = "POSITION_CLOSED",
        coin_id    = coin_id,
        symbol     = symbol,
        decision   = "SELL",
        severity   = "info" if pnl >= 0 else "warning",
        inputs     = {
            "entry_price": entry_price,
            "exit_price":  exit_price,
            "quantity":    quantity,
        },
        outputs = {
            "pnl_usdt": pnl,
            "pnl_pct":  pnl_pct,
            "reason":   reason,
        },
        cycle_id = cycle_id,
    ))


def log_regime_change(old_regime: str, new_regime: str, deviation_pct: float,
                       cycle_id: str = None):
    """Log un changement de régime de marché."""
    log_event(AuditEvent(
        event_type = "REGIME_CHANGED",
        decision   = new_regime,
        severity   = "warning",
        inputs     = {"old_regime": old_regime},
        outputs    = {"new_regime": new_regime, "btc_deviation_pct": deviation_pct},
        reasoning  = [f"Bascule {old_regime} -> {new_regime} (BTC {deviation_pct:+.2f}% vs EMA200)"],
        cycle_id   = cycle_id,
    ))


def log_circuit_event(event_type: str, severity: str, message: str,
                       metric: float = None, cycle_id: str = None):
    """Log un événement du circuit breaker."""
    log_event(AuditEvent(
        event_type = "CIRCUIT_BREAKER",
        decision   = event_type,
        severity   = severity,
        outputs    = {"metric": metric} if metric is not None else {},
        reasoning  = [message],
        cycle_id   = cycle_id,
    ))


def log_correlation_block(coin_id: str, correlated_with: str, correlation: float,
                           cycle_id: str = None):
    """Log un blocage d'entrée pour raison de corrélation."""
    log_event(AuditEvent(
        event_type = "CORRELATION_BLOCK",
        coin_id    = coin_id,
        decision   = "SKIP",
        severity   = "info",
        inputs     = {"correlated_with": correlated_with},
        outputs    = {"correlation": correlation},
        reasoning  = [f"Correlation {correlation:.3f} avec {correlated_with} > seuil"],
        cycle_id   = cycle_id,
    ))


def log_kelly_sizing(coin_id: str, win_rate: float, avg_win: float, avg_loss: float,
                     kelly_f: float, fractional_kelly: float, final_size_usdt: float,
                     cycle_id: str = None):
    """Log un calcul de dimensionnement Kelly."""
    log_event(AuditEvent(
        event_type = "KELLY_SIZING",
        coin_id    = coin_id,
        severity   = "info",
        inputs = {
            "win_rate": win_rate,
            "avg_win":  avg_win,
            "avg_loss": avg_loss,
        },
        outputs = {
            "kelly_full":    kelly_f,
            "kelly_used":    fractional_kelly,
            "size_usdt":     final_size_usdt,
        },
        cycle_id = cycle_id,
    ))


def log_cycle_completed(cycle_id: str, regime: str, positions_open: int,
                         capital: float, new_entries: int, exits: int):
    """Log le résumé d'un cycle complet."""
    log_event(AuditEvent(
        event_type = "CYCLE_COMPLETED",
        severity   = "info",
        outputs = {
            "regime":         regime,
            "positions":      positions_open,
            "capital_usdt":   capital,
            "new_entries":    new_entries,
            "exits":          exits,
        },
        cycle_id = cycle_id,
    ))


# ─── Requêtes ─────────────────────────────────────────────────────────────────

def query_events(event_type: str = None, coin_id: str = None,
                 cycle_id: str = None, severity: str = None,
                 since: str = None, limit: int = 100) -> list[dict]:
    """Interroge l'audit trail avec filtres. Retourne les events du plus récent au plus ancien."""
    from core.database import get_connection

    where = []
    params = []
    if event_type:
        where.append("event_type = ?"); params.append(event_type)
    if coin_id:
        where.append("coin_id = ?"); params.append(coin_id)
    if cycle_id:
        where.append("cycle_id = ?"); params.append(cycle_id)
    if severity:
        where.append("severity = ?"); params.append(severity)
    if since:
        where.append("created_at >= ?"); params.append(since)

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    query = (f"SELECT * FROM audit_log {where_clause} "
             f"ORDER BY created_at DESC LIMIT ?")
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["inputs"]  = json.loads(d.pop("inputs_json",  "{}"))
                d["outputs"] = json.loads(d.pop("outputs_json", "{}"))
                d["reasoning"] = json.loads(d.get("reasoning") or "[]")
            except (json.JSONDecodeError, TypeError):
                d["inputs"] = {}
                d["outputs"] = {}
                d["reasoning"] = []
            result.append(d)
        return result


def cycle_summary(cycle_id: str) -> dict:
    """Reconstitue la timeline complète d'un cycle."""
    events = query_events(cycle_id=cycle_id, limit=500)
    events.reverse()   # du plus ancien au plus récent

    summary = {
        "cycle_id":         cycle_id,
        "event_count":      len(events),
        "types":            {},
        "signals_analyzed": 0,
        "entries":          0,
        "exits":            0,
        "warnings":         0,
        "events":           events,
    }
    for e in events:
        t = e["event_type"]
        summary["types"][t] = summary["types"].get(t, 0) + 1
        if t == "SIGNAL_ANALYZED":  summary["signals_analyzed"] += 1
        if t == "ENTRY_EXECUTED":    summary["entries"] += 1
        if t == "POSITION_CLOSED":   summary["exits"] += 1
        if e["severity"] == "warning": summary["warnings"] += 1
    return summary


def purge_old_events(days: int = 30):
    """Purge les événements plus vieux que N jours."""
    from core.database import get_connection
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM audit_log WHERE created_at < ?", (cutoff,))
        return cur.rowcount
