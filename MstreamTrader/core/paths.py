"""
MstreamTrader - Gestion centralisée des chemins de stockage.
=============================================================

Sur ANDROID (via Buildozer/python-for-android), le code Python est extrait
dans `/data/data/<package>/files/app/` qui peut être volatile ou
read-only après réinstallation/mise à jour de l'APK.

Pour persister les données utilisateur (DB SQLite, clés API chiffrées,
logs, backups, exports), il faut utiliser le **storage privé de l'app** :
    /data/data/com.mstream.mstreamtrader/files/

Ce dossier est :
  - Lecture / écriture
  - Privé à l'app (autres apps n'y ont pas accès)
  - Survit aux mises à jour de l'APK
  - Effacé seulement à la désinstallation

Sur DESKTOP (Windows/Linux/macOS), on garde le path projet (à côté du code)
pour permettre le développement et le testing facile.

Ce module est importé par database, crypto, backup, export, logging_setup,
equity_history.
"""

import os
import sys
from pathlib import Path


def _detect_storage_dir() -> Path:
    """
    Détecte le bon répertoire de stockage selon la plateforme.

    Sur Android (P4A) :
      - Variable d'env ANDROID_ARGUMENT est définie
      - On utilise android.storage.app_storage_path() qui retourne
        /data/data/<package>/files/
      - Fallback : os.environ['ANDROID_PRIVATE'] si dispo
      - Fallback ultime : home directory
    Sur Desktop :
      - Path relatif au fichier source (à côté du code, comme avant)
    """
    # ── Android (Python For Android) ──
    if 'ANDROID_ARGUMENT' in os.environ or 'ANDROID_PRIVATE' in os.environ:
        try:
            from android.storage import app_storage_path
            p = Path(app_storage_path())
            p.mkdir(parents=True, exist_ok=True)
            return p
        except (ImportError, OSError):
            pass

        # Fallback 1 : variable d'env P4A
        priv = os.environ.get('ANDROID_PRIVATE')
        if priv:
            p = Path(priv)
            p.mkdir(parents=True, exist_ok=True)
            return p

        # Fallback 2 : home (toujours accessible)
        return Path.home()

    # ── Desktop : path projet (comme avant) ──
    return Path(__file__).resolve().parent.parent.parent


STORAGE_DIR: Path = _detect_storage_dir()
"""Racine de stockage persistant — DB, secrets, logs, backups vont là."""


# Sous-dossiers standards (créés à la demande)
LOGS_DIR    = STORAGE_DIR / "logs"
BACKUPS_DIR = STORAGE_DIR / "backups"
EXPORTS_DIR = STORAGE_DIR / "exports"


# Fichiers de premier niveau
DB_FILE   = STORAGE_DIR / "mstream_trader.db"
SALT_FILE = STORAGE_DIR / ".mstream_salt"


def is_android() -> bool:
    """True si on tourne sous Android (utilisé pour des branches conditionnelles)."""
    return 'ANDROID_ARGUMENT' in os.environ or 'ANDROID_PRIVATE' in os.environ


def storage_summary() -> dict:
    """Petit récap pour le debug (utile dans la status bar de l'UI)."""
    return {
        "platform":   sys.platform,
        "is_android": is_android(),
        "storage":    str(STORAGE_DIR),
        "db":         str(DB_FILE),
        "db_exists":  DB_FILE.exists(),
        "salt":       str(SALT_FILE),
        "logs":       str(LOGS_DIR),
    }
