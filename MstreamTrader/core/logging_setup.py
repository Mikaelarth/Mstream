"""
MstreamTrader - Configuration centralisée du logging
======================================================

Logger rotatif quotidien avec rétention configurable pour :
  - Debug post-mortem (crashes, erreurs, anomalies)
  - Audit historique des décisions du Bot Maître
  - Analyse de performance / comportement

Format : `YYYY-MM-DD HH:MM:SS.mmm [LEVEL] [logger_name] message`

Usage (une seule fois au démarrage de l'app) :
    from core.logging_setup import setup_logging
    setup_logging()

Tous les `logger.info/warning/error` du projet écrivent ensuite dans
`logs/mstream_YYYY-MM-DD.log` + console.

Rotation automatique à minuit, rétention 30 jours par défaut.
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


# Répertoire des logs (à côté de la DB)
_LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

# Format standard du projet
_LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)-7s] [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO,
                   retention_days: int = 30,
                   console: bool = True,
                   logfile: bool = True) -> None:
    """
    Configure le logging du projet.

    Args:
        level          : niveau minimum (DEBUG/INFO/WARNING/ERROR).
        retention_days : nombre de fichiers quotidiens à conserver.
        console        : activer sortie console (stdout).
        logfile        : activer sortie fichier rotatif.

    Idempotent : appelable plusieurs fois sans duplication de handlers.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Supprimer les handlers existants pour éviter les duplications
    # (utile si setup_logging est appelé plusieurs fois)
    for h in list(root.handlers):
        if getattr(h, "_mstream_handler", False):
            root.removeHandler(h)
            try:
                h.close()
            except (OSError, ValueError):
                pass

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # ── Console handler ──
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        console_handler._mstream_handler = True
        root.addHandler(console_handler)

    # ── File handler avec rotation quotidienne ──
    if logfile:
        try:
            _LOGS_DIR.mkdir(parents=True, exist_ok=True)
            file_path = _LOGS_DIR / "mstream.log"
            file_handler = TimedRotatingFileHandler(
                filename=str(file_path),
                when="midnight",           # rotation à minuit
                interval=1,                # tous les jours
                backupCount=retention_days,
                encoding="utf-8",
                delay=True,                # ouverture différée (évite un fichier vide au démarrage)
            )
            # Suffix lisible : mstream.log.2026-04-25
            file_handler.suffix = "%Y-%m-%d"
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            file_handler._mstream_handler = True
            root.addHandler(file_handler)
        except OSError as exc:
            # Fallback : console-only si écriture fichier impossible (Android
            # sandbox, permissions). Ne bloque jamais le bot.
            logging.getLogger("logging_setup").warning(
                f"File logging indisponible : {exc}"
            )


def get_logs_dir() -> Path:
    """Retourne le chemin absolu du dossier de logs."""
    return _LOGS_DIR


def list_available_logs() -> list[Path]:
    """Liste les fichiers de logs disponibles (pour UI / debug)."""
    if not _LOGS_DIR.exists():
        return []
    return sorted(_LOGS_DIR.glob("mstream.log*"))
