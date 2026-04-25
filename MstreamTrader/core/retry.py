"""
MstreamTrader - Retry automatique avec backoff exponentiel
===========================================================

Décorateur pour rendre robustes les appels API aux erreurs transitoires :
  - Timeout réseau
  - HTTP 503 / 504 (service unavailable)
  - Binance -1003 (rate limit) / -1001 (disconnected)
  - Erreurs parsing JSON temporaires

Stratégie : backoff exponentiel avec jitter (recommandé AWS).
  Attempt 1: immédiat
  Attempt 2: 0.5s + jitter
  Attempt 3: 1.0s + jitter
  Attempt 4: 2.0s + jitter
  (doublage jusqu'à max_delay)

Erreurs NON-retriées (échec permanent, remontée immédiate) :
  - Clés API invalides (-2015, -2014)
  - Ordre rejeté logique (LOT_SIZE, MIN_NOTIONAL, INSUFFICIENT_BALANCE)
  - 400 / 401 / 403 / 404

Utilisation :
    @retry_binance(max_attempts=3)
    def place_market_order(...):
        ...
"""

import functools
import logging
import random
import time
import urllib.error
from typing import Callable


logger = logging.getLogger("retry")

# Codes erreur Binance que l'on retry (transitoires)
_RETRYABLE_BINANCE_CODES = {
    -1000,    # UNKNOWN
    -1001,    # DISCONNECTED
    -1003,    # TOO_MANY_REQUESTS (rate limit)
    -1006,    # UNEXPECTED_RESP
    -1007,    # TIMEOUT
    -1016,    # SERVICE_SHUTTING_DOWN
    -1021,    # INVALID_TIMESTAMP (retry avec nouveau ts)
}

# Codes HTTP à retry
_RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}


def _is_retryable_error(exc: Exception) -> bool:
    """Détermine si une exception est transitoire (à retry) ou permanente."""
    # HTTPError est une sous-classe de URLError → tester en premier (plus spécifique)
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _RETRYABLE_HTTP_CODES

    # Erreurs réseau pures (timeout, connection reset, DNS)
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return True

    # BinanceError : parser le code dans le message
    from core.exchange import BinanceError
    if isinstance(exc, BinanceError):
        msg = str(exc).lower()
        # Check code Binance dans le message
        for code in _RETRYABLE_BINANCE_CODES:
            if f"binance {abs(code)}" in msg or f"code {code}" in msg or str(code) in msg:
                return True
        # Patterns de messages transitoires
        transient_patterns = [
            "too many requests", "timeout", "service unavailable",
            "connexion impossible", "rate limit",
        ]
        return any(p in msg for p in transient_patterns)

    return False


def retry_binance(max_attempts: int = 3,
                    initial_delay: float = 0.5,
                    max_delay: float = 10.0,
                    backoff_factor: float = 2.0,
                    jitter: bool = True) -> Callable:
    """
    Décorateur : retry une fonction en cas d'erreur Binance transitoire.

    Args:
        max_attempts   : nombre total de tentatives (1 = pas de retry).
        initial_delay  : délai avant le 1er retry (en secondes).
        max_delay      : délai maximum entre retries.
        backoff_factor : multiplicateur de délai à chaque échec.
        jitter         : ajoute un random ±25% pour éviter les synchronisations.

    Exemple :
        @retry_binance(max_attempts=3)
        def place_order(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if not _is_retryable_error(exc):
                        # Erreur permanente : remontée immédiate (pas de retry)
                        raise
                    if attempt >= max_attempts:
                        logger.warning(
                            f"[retry] {func.__name__} : max_attempts ({max_attempts}) atteint, "
                            f"derniere erreur : {exc}"
                        )
                        raise
                    # Calcul du délai avec backoff + jitter
                    sleep_time = min(delay, max_delay)
                    if jitter:
                        sleep_time *= (1.0 + random.uniform(-0.25, 0.25))
                    logger.info(
                        f"[retry] {func.__name__} : attempt {attempt}/{max_attempts} "
                        f"failed ({type(exc).__name__}: {exc}), retry in {sleep_time:.2f}s"
                    )
                    time.sleep(max(0.0, sleep_time))
                    delay *= backoff_factor
            # Inatteignable (raise dans la boucle), mais pour mypy
            if last_exc:
                raise last_exc
            return None
        return wrapper
    return decorator
