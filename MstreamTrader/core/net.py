"""
MstreamTrader - Helpers réseau partagés (SSL context, error decoding).

Sur ANDROID via Buildozer/python-for-android, urllib HTTPS échoue
silencieusement si le contexte SSL ne pointe pas vers une chaîne de
certificats valide. Ce module centralise la construction du contexte
SSL pour tous les appels HTTPS de l'app (CoinGecko, Binance, Telegram).

Stratégie de fallback :
  1. certifi (le standard) — bundlé via buildozer.spec
  2. Bundle CA système Android (/system/etc/security/cacerts/)
  3. ssl.create_default_context() (fallback final)

Si TOUT échoue, on retourne None (l'appelant peut continuer sans
contexte = comportement urllib par défaut). Mais si certifi est
correctement bundlé dans l'APK, on devrait toujours avoir un contexte.
"""

import logging
import os
import ssl
from typing import Optional


logger = logging.getLogger("net")


def _build_ssl_context() -> Optional[ssl.SSLContext]:
    """Construit un contexte SSL robuste qui marche sur Android."""
    # 1. certifi (standard PyPI, bundlé via requirements buildozer)
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return ctx
    except ImportError:
        pass
    except (ssl.SSLError, OSError) as exc:
        logger.warning(f"SSL context certifi failed : {exc}")

    # 2. Bundle système Android typique
    for ca in ("/etc/security/cacerts", "/system/etc/security/cacerts"):
        try:
            if os.path.isdir(ca):
                ctx = ssl.create_default_context(capath=ca)
                return ctx
        except (ssl.SSLError, OSError):
            continue

    # 3. Defaut (utilise les CA du système Python)
    try:
        return ssl.create_default_context()
    except (ssl.SSLError, OSError) as exc:
        logger.warning(f"SSL default context failed : {exc}")
        return None


# Contexte SSL partagé — créé une seule fois au démarrage de l'app
SSL_CTX: Optional[ssl.SSLContext] = _build_ssl_context()


def explain_url_error(exc: Exception) -> str:
    """
    Convertit une exception réseau en message lisible pour l'utilisateur.
    Distingue SSL, timeout, DNS, refused, etc.
    """
    import urllib.error

    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"

    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        reason_str = str(reason) if reason else str(exc)

        if isinstance(reason, ssl.SSLError):
            return f"SSL/TLS : {reason}"
        if "CERTIFICATE_VERIFY_FAILED" in reason_str:
            return "SSL : certificat invalide — vérifiez la connexion"
        if "Name or service not known" in reason_str or "nodename" in reason_str:
            return "DNS : impossible de résoudre l'adresse"
        if "timed out" in reason_str.lower():
            return "Timeout : Binance/serveur ne répond pas"
        if "Connection refused" in reason_str or "refused" in reason_str:
            return "Connexion refusée par le serveur"
        if "Network is unreachable" in reason_str:
            return "Réseau indisponible — pas d'Internet ?"
        return f"Réseau : {reason_str}"

    if isinstance(exc, TimeoutError):
        return "Timeout : pas de réponse"

    if isinstance(exc, OSError):
        return f"OS : {exc}"

    return str(exc)
