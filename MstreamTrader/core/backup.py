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

from core import paths


logger = logging.getLogger("backup")

# Emplacement par défaut (configurable via init_backup) — storage Android-safe
_DEFAULT_BACKUP_DIR = paths.BACKUPS_DIR


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


def restore_from_backup(backup_path: Path,
                         confirm_overwrite: bool = False) -> bool:
    """
    Restaure la DB principale depuis un backup atomiquement.

    Args:
        backup_path       : chemin vers le fichier .db de backup à restaurer.
        confirm_overwrite : True pour confirmer écrasement de la DB en cours.
                            Sécurité : sans ça, refus si DB cible existe.

    Stratégie atomique en 3 étapes :
      1. Renommer DB actuelle en `<db>.before_restore_<TS>` (rollback possible)
      2. Utiliser sqlite3.Connection.backup() depuis le backup vers la DB
      3. Si OK : la sauvegarde de sécurité reste pour rollback manuel
         Si KO : on remet la sauvegarde en place

    Retourne True si la restauration a réussi, False sinon.
    """
    if not backup_path.exists():
        logger.error(f"Backup introuvable : {backup_path}")
        return False
    if not backup_path.is_file():
        logger.error(f"Backup n'est pas un fichier : {backup_path}")
        return False

    target = _get_source_db_path()
    safety_copy: Path | None = None

    try:
        # Vérifier que le backup est une DB SQLite valide AVANT toucher à la cible
        try:
            test_conn = sqlite3.connect(str(backup_path))
            test_conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            test_conn.close()
        except sqlite3.Error as exc:
            logger.error(f"Backup corrompu, refus de restaurer : {exc}")
            return False

        if target.exists() and not confirm_overwrite:
            logger.error(
                "DB cible existe et confirm_overwrite=False — refus."
            )
            return False

        # Étape 1 : safety copy de la DB actuelle (rollback possible)
        if target.exists():
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            safety_copy = target.parent / f"{target.name}.before_restore_{ts}"
            target.rename(safety_copy)
            logger.info(f"DB actuelle sauvegardee : {safety_copy.name}")

        # Étape 2 : copie atomique via API SQLite (pas un simple file copy)
        src = sqlite3.connect(str(backup_path))
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()

        logger.info(f"DB restauree depuis : {backup_path.name}")
        return True

    except (sqlite3.Error, OSError) as exc:
        logger.error(f"Echec restauration : {exc}")
        # Rollback : remettre la safety copy en place si elle existe
        if safety_copy is not None and safety_copy.exists():
            try:
                if target.exists():
                    target.unlink()
                safety_copy.rename(target)
                logger.info("Rollback effectue : DB precedente restauree")
            except OSError as rollback_exc:
                logger.error(f"Rollback impossible : {rollback_exc}")
        return False
