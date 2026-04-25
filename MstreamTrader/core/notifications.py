"""
MstreamTrader - Notifications Telegram
========================================

Envoi de messages Telegram pour les événements importants du bot :
  - ENTRY / EXIT de position (avec P&L)
  - Circuit Breaker : TRIGGERED / FROZEN / RECOVERED
  - Drawdown pause
  - Erreurs API répétées
  - Résumé quotidien (option, à 9h)

Utilise uniquement `urllib` (stdlib) pour rester compatible Android Buildozer
zero dépendance.

Configuration :
  - `telegram_bot_token` : token du bot (créé via @BotFather sur Telegram)
  - `telegram_chat_id`   : ID du chat où envoyer (peut être obtenu via @userinfobot)
  Les deux stockés en DB chiffrés (comme les clés Binance).

Mode silencieux automatique si le token ou chat_id manquent → le bot continue
de fonctionner sans notifications.

Thread-safe : les envois réseau se font dans un thread séparé (non-bloquant).
"""

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional

from core.net import SSL_CTX, explain_url_error


logger = logging.getLogger("notifications")

_TELEGRAM_BASE = "https://api.telegram.org/bot{token}/{method}"
_REQUEST_TIMEOUT = 10
_MIN_INTERVAL_BETWEEN_MSG = 0.5   # anti-flood : pas plus d'un message / 0.5s


# ─── Configuration helpers ────────────────────────────────────────────────────

def is_configured() -> bool:
    """Retourne True si le bot Telegram est configuré (token + chat_id)."""
    from core.database import get_setting_encrypted
    token = get_setting_encrypted("telegram_bot_token")
    chat_id = get_setting_encrypted("telegram_chat_id")
    return bool(token) and bool(chat_id)


def set_credentials(bot_token: str, chat_id: str) -> None:
    """Sauvegarde les credentials chiffrés."""
    from core.database import set_setting_encrypted
    set_setting_encrypted("telegram_bot_token", bot_token.strip())
    set_setting_encrypted("telegram_chat_id",    chat_id.strip())
    logger.info("[Telegram] Credentials sauvegardes (chiffres)")


def clear_credentials() -> None:
    """Retire les credentials (désactive les notifications)."""
    from core.database import set_setting_encrypted
    set_setting_encrypted("telegram_bot_token", "")
    set_setting_encrypted("telegram_chat_id",    "")


# ─── Rate limiter simple ──────────────────────────────────────────────────────

_last_send_ts = 0.0
_send_lock    = threading.Lock()


def _enforce_rate_limit():
    """Évite de spammer Telegram (max 1 msg / 0.5s)."""
    global _last_send_ts
    with _send_lock:
        elapsed = time.time() - _last_send_ts
        if elapsed < _MIN_INTERVAL_BETWEEN_MSG:
            time.sleep(_MIN_INTERVAL_BETWEEN_MSG - elapsed)
        _last_send_ts = time.time()


# ─── Envoi bas niveau ─────────────────────────────────────────────────────────

def _send_telegram_sync(text: str, silent: bool = False) -> bool:
    """
    Envoi synchrone d'un message Telegram. Retourne True si succès.
    Utilisé en interne, à NE PAS appeler directement depuis le bot (bloquant).
    """
    from core.database import get_setting_encrypted
    token = get_setting_encrypted("telegram_bot_token")
    chat_id = get_setting_encrypted("telegram_chat_id")

    if not token or not chat_id:
        return False   # silent fail : pas de config

    _enforce_rate_limit()

    url = _TELEGRAM_BASE.format(token=token, method="sendMessage")
    data = urllib.parse.urlencode({
        "chat_id":            chat_id,
        "text":               text[:4000],   # limite Telegram
        "parse_mode":         "HTML",
        "disable_notification": "true" if silent else "false",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data)
        # context=SSL_CTX critique sur Android — sinon HTTPS Telegram échoue
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT,
                                     context=SSL_CTX) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("ok"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        logger.warning(f"[Telegram] Send failed (network) : {explain_url_error(exc)}")
        return False
    except (ValueError, KeyError) as exc:
        logger.warning(f"[Telegram] Send failed (parse) : {exc}")
        return False


# ─── API publique async ────────────────────────────────────────────────────────

def send_async(text: str, silent: bool = False) -> None:
    """
    Envoie un message Telegram en tâche de fond (ne bloque PAS le bot).
    Idempotent si pas configuré → silent fail.
    """
    if not is_configured():
        return
    thread = threading.Thread(
        target=_send_telegram_sync,
        args=(text, silent),
        daemon=True,
    )
    thread.start()


# ─── Helpers spécifiques aux événements du bot ────────────────────────────────

def notify_entry(coin_id: str, symbol: str, entry_price: float, quantity: float,
                  amount_usdt: float, sl: float, tp: float, regime: str,
                  profile: str = None) -> None:
    """Notification d'ouverture de position."""
    profile_str = f"\n📋 Profil : <b>{profile}</b>" if profile else ""
    msg = (
        f"🟢 <b>ENTRY</b> {symbol}\n"
        f"💰 Prix : {entry_price:.4f}\n"
        f"📦 Quantité : {quantity:.6f}\n"
        f"💵 Montant : ${amount_usdt:,.2f}\n"
        f"🛑 SL : {sl:.4f}\n"
        f"🎯 TP : {tp:.4f}\n"
        f"📊 Régime : <b>{regime.upper()}</b>"
        f"{profile_str}"
    )
    send_async(msg)


def notify_exit(coin_id: str, symbol: str, entry_price: float, exit_price: float,
                 pnl: float, r_multiple: float, reason: str) -> None:
    """Notification de clôture de position (TP ou SL)."""
    emoji = "✅" if pnl > 0 else "🔴"
    reason_label = {"EXIT_TP": "Take-Profit", "EXIT_SL": "Stop-Loss"}.get(reason, reason)
    pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
    msg = (
        f"{emoji} <b>EXIT</b> {symbol} ({reason_label})\n"
        f"📈 Entrée : {entry_price:.4f}\n"
        f"📉 Sortie : {exit_price:.4f} ({pnl_pct:+.2f}%)\n"
        f"💵 P&L : <b>{pnl:+.2f} USDT</b>\n"
        f"📊 R-multiple : <b>{r_multiple:+.2f}R</b>"
    )
    send_async(msg)


def notify_circuit_breaker(state: str, message: str = "") -> None:
    """Notification de changement d'état du Circuit Breaker."""
    emoji = {
        "HEALTHY":   "🟢",
        "WARNING":   "🟡",
        "TRIGGERED": "🟠",
        "FROZEN":    "🔴",
    }.get(state.upper(), "⚠️")
    msg = (
        f"{emoji} <b>Circuit Breaker : {state.upper()}</b>\n"
        f"{message}"
    )
    send_async(msg)


def notify_drawdown_pause(drawdown_pct: float, max_allowed: float) -> None:
    """Notification de pause sur drawdown max atteint."""
    msg = (
        f"⚠️ <b>DRAWDOWN PAUSE</b>\n"
        f"Drawdown actuel : <b>{drawdown_pct:.2f}%</b>\n"
        f"Max autorisé : {max_allowed:.2f}%\n"
        f"Trading suspendu — les positions ouvertes restent surveillées."
    )
    send_async(msg)


def notify_daily_summary(total_trades: int, wins: int, pnl_day: float,
                           capital: float, roi_pct: float) -> None:
    """Résumé quotidien (appelé à heure fixe ou au changement de jour)."""
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    emoji = "📈" if pnl_day >= 0 else "📉"
    msg = (
        f"{emoji} <b>Résumé du {datetime.now().strftime('%d/%m/%Y')}</b>\n"
        f"Trades : <b>{total_trades}</b> ({wins} wins, WR {win_rate:.1f}%)\n"
        f"P&L jour : <b>{pnl_day:+.2f} USDT</b>\n"
        f"Capital : <b>${capital:,.2f}</b>\n"
        f"ROI total : <b>{roi_pct:+.2f}%</b>"
    )
    send_async(msg, silent=True)


def notify_error(error_type: str, message: str) -> None:
    """Notification d'erreur critique (API down, bug, etc.)."""
    msg = (
        f"🛠️ <b>ERREUR : {error_type}</b>\n"
        f"{message[:500]}"
    )
    send_async(msg)


def test_connection() -> tuple[bool, str]:
    """
    Envoie un message test pour valider la config.
    Retourne (success, message_status).
    """
    if not is_configured():
        return False, "Credentials non configurés"
    ok = _send_telegram_sync("🤖 <b>MstreamTrader</b>\nConnexion Telegram OK !")
    return ok, "Message test envoyé" if ok else "Échec d'envoi (vérifier token/chat_id)"
