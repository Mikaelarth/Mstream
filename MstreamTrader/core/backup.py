"""
MstreamTrader - Backup automatique de la base SQLite
=====================================================

Snapshot de la DB toutes les 24h avec rétention 7 jours.
Utilise l'API backup atomique de sqlite3 (safe même pendant un write concurrent).

Scénario protégé :
  - Corruption DB (rare mais arrive)
  - Suppression accidentelle
  - Mauvaise migration
  - Crash pendant un write non-WAL

Format : backups/mstream_trader_YYYY-MM-DD_HHMM.db
Appelé par le bot tous les N cycles (voir auto_trader.py).
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


logger = logging.getLogger("backup")

# Emplacement par défaut (configurable via init_backup)
_DEFAULT_BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "backups"


def _get_source_db_path() -> Path:
    """Retourne le path de la DB source (lu depuis database.py)."""
    from core.database import DB_PATH
    return Path(DB_PATH)


def create_backup(backup_dir: Path = None) -> Path | None:
    """
    Crée un snapshot atomique de la DB.

    Utilise `sqlite3.Connection.backup()` qui est safe même si la DB est
    en cours d'écriture (mode WAL).

    Retourne le path du fichier créé, None si échec.
    """
    backup_dir = backup_dir or _DEFAULT_BACKUP_DIR
    source_path = _get_source_db_path()

    if not source_path.exists():
        logger.warning(f"Source DB absente : {source_path}")
        return None

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        target_path = backup_dir / f"mstream_trader_{ts}.db"

        # Backup atomique via API sqlite3 (pas juste copy de fichier)
        source_conn = sqlite3.connect(str(source_path))
        target_conn = sqlite3.connect(str(target_path))
        try:
            source_conn.backup(target_conn)
        finally:
            source_conn.close()
            target_conn.close()

        logger.info(f"Backup DB cree : {target_path.name}")
        return target_path

    except (sqlite3.Error, OSError) as exc:
        logger.error(f"Echec backup DB : {exc}")
        return None


def purge_old_backups(backup_dir: Path = None,
                      retention_days: int = 7) -> int:
    """
    Supprime les backups plus vieux que retention_days.
    Retourne le nombre de fichiers supprimés.
    """
    backup_dir = backup_dir or _DEFAULT_BACKUP_DIR
    if not backup_dir.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for f in backup_dir.glob("mstream_trader_*.db"):
        try:
            # Extraire la date depuis le nom du fichier (format YYYY-MM-DD_HHMM)
            stem = f.stem.replace("mstream_trader_", "")
            dt = datetime.strptime(stem, "%Y-%m-%d_%H%M")
            if dt < cutoff:
                f.unlink()
                removed += 1
                logger.info(f"Backup expire supprime : {f.name}")
        except (ValueError, OSError) as exc:
            logger.debug(f"Skip {f.name}: {exc}")
    return removed


def list_backups(backup_dir: Path = None) -> list[Path]:
    """Liste les backups disponibles, triés du plus récent au plus ancien."""
    backup_dir = backup_dir or _DEFAULT_BACKUP_DIR
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob("mstream_trader_*.db"), reverse=True)


def create_backup_and_purge(backup_dir: Path = None,
                             retention_days: int = 7) -> Path | None:
    """Helper pratique : créer un backup puis purger les anciens."""
    result = create_backup(backup_dir)
    purge_old_backups(backup_dir, retention_days)
    return result
