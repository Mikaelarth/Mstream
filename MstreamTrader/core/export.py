"""
MstreamTrader - Export des données utilisateur
================================================

Export CSV des trades pour analyse externe (Excel, déclarations fiscales,
backtesting custom). Fichiers sauvegardés dans `exports/` à côté de la DB.

Usage :
    from core.export import export_trades_to_csv
    path = export_trades_to_csv()                            # tous les trades
    path = export_trades_to_csv(start_date="2026-01-01")     # depuis une date
    path = export_trades_to_csv(portfolio_type="master")     # filtre portfolio
"""

import csv
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from core import paths


logger = logging.getLogger("export")

_EXPORT_DIR = paths.EXPORTS_DIR


def export_trades_to_csv(start_date: Optional[str] = None,
                          end_date:   Optional[str] = None,
                          portfolio_type: Optional[str] = None,
                          output_path: Optional[Path] = None) -> Optional[Path]:
    """
    Exporte les trades en CSV.

    Args:
        start_date     : 'YYYY-MM-DD' inclusif. None = depuis l'origine.
        end_date       : 'YYYY-MM-DD' inclusif. None = jusqu'à aujourd'hui.
        portfolio_type : 'master', 'master_paper', 'securite', 'libre', None = tous.
        output_path    : chemin de sortie. None = exports/trades_<TS>.csv auto.

    Retourne le path du fichier créé ou None si échec.
    """
    from core.database import get_connection

    where = ["1=1"]
    params = []
    if start_date:
        where.append("DATE(executed_at) >= ?"); params.append(start_date)
    if end_date:
        where.append("DATE(executed_at) <= ?"); params.append(end_date)
    if portfolio_type:
        # Match les sources qui contiennent ce portfolio_type
        where.append("source LIKE ?"); params.append(f"%{portfolio_type.upper()}%")

    sql = f"""SELECT id, executed_at, side, coin_id, symbol,
                     quantity, price, total_usdt, fee, source, note, exchange_id
              FROM trades
              WHERE {' AND '.join(where)}
              ORDER BY executed_at ASC"""

    try:
        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.error(f"Export query failed : {exc}")
        return None

    if not rows:
        logger.info("Aucun trade à exporter pour ces critères")
        return None

    # Détermine le path de sortie
    if output_path is None:
        _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = _EXPORT_DIR / f"trades_{ts}.csv"

    headers = [
        "id", "executed_at", "side", "coin_id", "symbol",
        "quantity", "price", "total_usdt", "fee", "source", "note", "exchange_id",
    ]

    try:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for r in rows:
                writer.writerow([
                    r["id"], r["executed_at"], r["side"], r["coin_id"], r["symbol"],
                    r["quantity"], r["price"], r["total_usdt"], r["fee"],
                    r["source"], r["note"] or "", r["exchange_id"] or "",
                ])
        logger.info(f"Export CSV : {len(rows)} trades → {output_path.name}")
        return output_path
    except OSError as exc:
        logger.error(f"Echec ecriture CSV : {exc}")
        return None


def list_exports() -> list[Path]:
    """Liste les exports disponibles."""
    if not _EXPORT_DIR.exists():
        return []
    return sorted(_EXPORT_DIR.glob("trades_*.csv"), reverse=True)
