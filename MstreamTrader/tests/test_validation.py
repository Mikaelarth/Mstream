"""
Tests pytest : validation des configurations utilisateur.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.validation import validate_setting


def test_budget_negative_rejected():
    ok, msg = validate_setting("budget_master", "-100")
    assert ok is False
    assert "min" in msg.lower()


def test_budget_too_large_rejected():
    ok, msg = validate_setting("budget_master", "99999999")
    assert ok is False
    assert "max" in msg.lower()


def test_budget_valid_accepted():
    ok, msg = validate_setting("budget_master", "1000.0")
    assert ok is True


def test_risk_too_high_rejected():
    ok, msg = validate_setting("risk_master", "99")
    assert ok is False


def test_risk_valid_accepted():
    ok, msg = validate_setting("risk_master", "5.0")
    assert ok is True


def test_telegram_chat_id_must_be_numeric():
    ok, msg = validate_setting("telegram_chat_id", "not_a_number")
    assert ok is False
    assert "nombre" in msg.lower()


def test_telegram_chat_id_negative_accepted():
    """IDs de groupes Telegram sont négatifs, ça doit passer."""
    ok, _ = validate_setting("telegram_chat_id", "-1001234567890")
    assert ok is True


def test_telegram_token_format():
    ok, msg = validate_setting("telegram_bot_token", "invalid")
    assert ok is False
    ok, _ = validate_setting(
        "telegram_bot_token",
        "123456:ABCDEFghijklmnopqrstuvwxyz01234-_"
    )
    assert ok is True


def test_api_key_too_short():
    ok, msg = validate_setting("binance_api_key", "abc")
    assert ok is False


def test_unknown_setting_accepted_by_default():
    """Une clé sans règle est acceptée par défaut."""
    ok, _ = validate_setting("random_unknown_key", "any_value")
    assert ok is True


def test_non_numeric_for_numeric_field():
    ok, msg = validate_setting("risk_master", "not a number")
    assert ok is False
    assert "non numérique" in msg.lower() or "non numerique" in msg.lower()
