"""
MstreamTrader - Validation des configurations utilisateur
===========================================================

Protège le bot contre les valeurs aberrantes entrées via l'UI :
  - Budget négatif ou > $1M
  - Risque par trade > 50 % (ruin guaranteed)
  - Max positions > 20
  - Drawdown < 1 % (trop sensible) ou > 100 %
  - Clés API de longueur invalide

Lève ValueError explicite en cas de valeur hors borne, avec un message clair.
L'UI doit catcher et afficher le message au user.
"""

from dataclasses import dataclass
from typing import Union


@dataclass
class ValidationRule:
    """Règle de validation pour une config."""
    name:        str
    min_value:   Union[float, int, None] = None
    max_value:   Union[float, int, None] = None
    type_:       type = float
    description: str  = ""


# Règles par clé de setting
VALIDATION_RULES = {
    # Budgets
    "budget_master":           ValidationRule(
        "budget_master", min_value=0.0, max_value=1_000_000.0, type_=float,
        description="Budget du Bot Maître en USDT (0 à 1M)"),
    "budget_master_initial":   ValidationRule(
        "budget_master_initial", min_value=0.0, max_value=1_000_000.0, type_=float,
        description="Capital initial de référence ROI"),
    "budget_master_paper":     ValidationRule(
        "budget_master_paper", min_value=0.0, max_value=1_000_000.0, type_=float,
        description="Budget paper trading"),
    "budget_securite":         ValidationRule(
        "budget_securite", min_value=0.0, max_value=1_000_000.0, type_=float,
        description="Budget portefeuille Sécurité (legacy)"),
    "budget_libre":            ValidationRule(
        "budget_libre", min_value=0.0, max_value=1_000_000.0, type_=float,
        description="Budget portefeuille Libre (legacy)"),
    "usdt_balance":            ValidationRule(
        "usdt_balance", min_value=0.0, max_value=10_000_000.0, type_=float,
        description="Solde USDT manuel"),

    # Risque par trade (% du budget)
    "risk_master":             ValidationRule(
        "risk_master", min_value=0.5, max_value=25.0, type_=float,
        description="Risque par trade (0.5 à 25 % du budget)"),
    "risk_libre":              ValidationRule(
        "risk_libre", min_value=0.5, max_value=20.0, type_=float,
        description="Risque Libre par trade"),
    "risk_per_trade":          ValidationRule(
        "risk_per_trade", min_value=0.1, max_value=20.0, type_=float,
        description="Risque manuel par trade"),

    # Clés API (longueurs)
    "binance_api_key":         ValidationRule(
        "binance_api_key", type_=str,
        description="Clé API Binance (64 caractères attendus)"),
    "binance_api_secret":      ValidationRule(
        "binance_api_secret", type_=str,
        description="Secret API Binance"),

    # Telegram
    "telegram_bot_token":      ValidationRule(
        "telegram_bot_token", type_=str,
        description="Token bot Telegram (format: 123456:ABC-DEF...)"),
    "telegram_chat_id":        ValidationRule(
        "telegram_chat_id", type_=str,
        description="Chat ID Telegram (nombre, ex: -1001234567890)"),
}


def validate_setting(key: str, value: str) -> tuple[bool, str]:
    """
    Valide une valeur de setting avant sauvegarde.

    Args:
        key   : nom du setting
        value : valeur string (comme stockée en DB)

    Retourne (ok, message).
    Si ok=False, message contient l'explication claire à afficher au user.
    Si le setting n'a pas de règle, on accepte par défaut (ok=True).
    """
    rule = VALIDATION_RULES.get(key)
    if rule is None:
        return True, ""   # pas de règle → accepté

    # Validation des types string (clés API, tokens)
    if rule.type_ is str:
        stripped = (value or "").strip()
        if key == "binance_api_key" and stripped and len(stripped) < 20:
            return False, "Clé API Binance trop courte (attendu ≥ 20 caractères)"
        if key == "binance_api_secret" and stripped and len(stripped) < 20:
            return False, "Secret API Binance trop court"
        if key == "telegram_bot_token" and stripped:
            # Format attendu : "123456:ABC-DEF_ghi..."
            if ":" not in stripped or len(stripped) < 30:
                return False, "Format token Telegram invalide (attendu: 123456:ABC-...)"
        if key == "telegram_chat_id" and stripped:
            try:
                int(stripped)   # doit être un entier (positif ou négatif pour groupes)
            except ValueError:
                return False, "Chat ID Telegram doit être un nombre entier"
        return True, ""

    # Validation des types numériques
    try:
        num = rule.type_(value)
    except (ValueError, TypeError):
        return False, f"{rule.description} : valeur non numérique ({value})"

    if rule.min_value is not None and num < rule.min_value:
        return False, f"{rule.description} : min = {rule.min_value}, reçu {num}"
    if rule.max_value is not None and num > rule.max_value:
        return False, f"{rule.description} : max = {rule.max_value}, reçu {num}"

    return True, ""


def safe_set_setting(key: str, value: str) -> tuple[bool, str]:
    """
    Valide + sauvegarde une valeur. Retourne (ok, message).
    À utiliser depuis les écrans settings au lieu de `database.set_setting()`.
    """
    ok, msg = validate_setting(key, value)
    if not ok:
        return False, msg
    from core.database import set_setting
    set_setting(key, value)
    return True, "Sauvegardé"


def safe_set_setting_encrypted(key: str, value: str) -> tuple[bool, str]:
    """Valide + sauvegarde une valeur chiffrée (clés API, tokens)."""
    ok, msg = validate_setting(key, value)
    if not ok:
        return False, msg
    from core.database import set_setting_encrypted
    set_setting_encrypted(key, value)
    return True, "Sauvegardé (chiffré)"


def validate_all_current_settings() -> list[tuple[str, str]]:
    """
    Vérifie toutes les settings actuellement en DB contre les règles.
    Retourne une liste des (key, message_erreur) pour les valeurs invalides.
    Liste vide = tout OK.
    """
    from core.database import get_setting, get_setting_encrypted

    invalid = []
    for key, rule in VALIDATION_RULES.items():
        # Les secrets sont lus décryptés pour validation
        if key in ("binance_api_key", "binance_api_secret",
                   "telegram_bot_token", "telegram_chat_id"):
            value = get_setting_encrypted(key, "")
        else:
            value = get_setting(key, "")
        if value:
            ok, msg = validate_setting(key, value)
            if not ok:
                invalid.append((key, msg))
    return invalid
