"""
MstreamTrader - Historique d'équité (capital + ROI dans le temps)
====================================================================

Snapshot quotidien du capital total (réalisé + non-réalisé) pour permettre
le tracking et la visualisation graphique de l'évolution du portefeuille.

Stocké dans la table `equity_history` :
    (date YYYY-MM-DD, mode 'real'|'paper', capital, unrealized_pnl,
     realized_pnl_today, total_trades_today)

Une seule ligne par jour et par mode. UPSERT à chaque appel.
Appelé automatiquement par le bot lors du daily summary.

Utilisé par :
  - UI Portfolio : graph d'équité (Kivy)
  - Export user : analyse historique
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional


logger = logging.getLogger("equity_history")


def init_equity_table():
    """Crée la table si absente."""
    from core.database import get_connection
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS equity_history (
                date         TEXT NOT NULL,
                mode         TEXT NOT NULL DEFAULT 'real',
                capital      REAL NOT NULL,
                unrealized_pnl REAL NOT NULL DEFAULT 0,
                realized_pnl_today REAL NOT NULL DEFAULT 0,
                trades_today INTEGER NOT NULL DEFAULT 0,
                roi_pct      REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (date, mode)
            )
        """)


def record_snapshot(capital: float,
                     unrealized_pnl: float = 0.0,
                     realized_pnl_today: float = 0.0,
                     trades_today: int = 0,
                     roi_pct: float = 0.0,
                     mode: str = "real",
                     date: Optional[str] = None) -> None:
    """Enregistre (ou met à jour) le snapshot équité du jour."""
    from core.database import get_connection
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO equity_history
                   (date, mode, capital, unrealized_pnl, realized_pnl_today,
                    trades_today, roi_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(date, mode) DO UPDATE SET
                     capital=excluded.capital,
                     unrealized_pnl=excluded.unrealized_pnl,
                     realized_pnl_today=excluded.realized_pnl_today,
                     trades_today=excluded.trades_today,
                     roi_pct=excluded.roi_pct""",
                (date, mode, capital, unrealized_pnl,
                 realized_pnl_today, trades_today, roi_pct)
            )
    except (sqlite3.Error, ValueError, TypeError) as exc:
        logger.warning(f"record_snapshot failed: {exc}")


def get_history(days: int = 30, mode: str = "real") -> list[dict]:
    """Retourne les N derniers jours d'historique (du plus ancien au plus récent)."""
    from core.database import get_connection
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM equity_history
                   WHERE mode = ? AND date >= ?
                   ORDER BY date ASC""",
                (mode, cutoff)
            ).fetchall()
            return [dict(r) for r in rows]
    except (sqlite3.Error, ValueError, TypeError) as exc:
        logger.warning(f"get_history failed: {exc}")
        return []


def get_equity_curve(days: int = 30, mode: str = "real") -> list[tuple[str, float]]:
    """
    Retourne la courbe (date, capital) pour le graph UI.
    Liste vide si pas d'historique.
    """
    history = get_history(days, mode)
    return [(h["date"], h["capital"]) for h in history]
