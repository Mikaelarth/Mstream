"""
Tests pytest : module crypto (chiffrement des clés API au repos).

Sécurité-critique. On vérifie :
  - encrypt/decrypt sont inverses (roundtrip)
  - encrypt produit le préfixe ENC_PREFIX
  - decrypt accepte les valeurs en clair (compat ascendante)
  - chaîne vide gérée correctement
  - is_encrypted détecte le préfixe
  - keystream déterministe (pour le même salt) → encrypt deterministe
  - chiffré != clair (vérifie qu'il y a bien obfuscation)
  - Utilise le vrai salt sur disque (pas de mock — on teste le path complet)
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import crypto


# ─── Roundtrip ────────────────────────────────────────────────────────────────

def test_encrypt_decrypt_roundtrip():
    """encrypt(decrypt(x)) == x pour les chaînes ASCII."""
    plain = "my_secret_api_key_12345"
    enc = crypto.encrypt(plain)
    dec = crypto.decrypt(enc)
    assert dec == plain


def test_roundtrip_unicode():
    """Le module doit gérer les chaînes UTF-8 (caractères accentués, emoji)."""
    plain = "café_société_éàü_日本語"
    enc = crypto.encrypt(plain)
    dec = crypto.decrypt(enc)
    assert dec == plain


def test_roundtrip_long_string():
    """Strings > 32 octets utilisent le keystream étendu."""
    plain = "x" * 500
    enc = crypto.encrypt(plain)
    dec = crypto.decrypt(enc)
    assert dec == plain
    assert len(dec) == 500


def test_roundtrip_special_chars():
    plain = '!@#$%^&*()_+-={}[]|\\:";\'<>?,./~`'
    enc = crypto.encrypt(plain)
    assert crypto.decrypt(enc) == plain


# ─── Chaîne vide ──────────────────────────────────────────────────────────────

def test_encrypt_empty_returns_empty():
    assert crypto.encrypt("") == ""


def test_decrypt_empty_returns_empty():
    assert crypto.decrypt("") == ""


# ─── Préfixe ENC ──────────────────────────────────────────────────────────────

def test_encrypted_value_has_prefix():
    enc = crypto.encrypt("foo")
    assert enc.startswith(crypto.ENC_PREFIX)


def test_is_encrypted_detection():
    assert crypto.is_encrypted("enc:base64payload==") is True
    assert crypto.is_encrypted("plain_value") is False
    assert crypto.is_encrypted("") is False


# ─── Compat ascendante ────────────────────────────────────────────────────────

def test_decrypt_passthrough_legacy_plain():
    """Une valeur sans préfixe enc: doit être retournée telle quelle."""
    legacy_value = "my_old_unencrypted_api_key"
    assert crypto.decrypt(legacy_value) == legacy_value


def test_decrypt_corrupted_returns_empty():
    """ciphertext malformé (base64 invalide) → "" sans crash."""
    corrupt = crypto.ENC_PREFIX + "this_is_not_valid_base64!!!"
    result = crypto.decrypt(corrupt)
    assert result == ""


# ─── Sécurité : chiffré ≠ clair ───────────────────────────────────────────────

def test_ciphertext_differs_from_plaintext():
    """Vérifie qu'il y a bien obfuscation : le ciphertext ne contient pas le clair."""
    plain = "AKIAIOSFODNN7EXAMPLE"   # exemple de clé AWS-style
    enc = crypto.encrypt(plain)
    # Le préfixe "enc:" est attendu, mais le contenu base64 ne doit pas
    # contenir la chaîne en clair
    assert plain not in enc


def test_different_inputs_produce_different_outputs():
    """Deux clairs différents → deux ciphertexts différents."""
    enc_a = crypto.encrypt("api_key_alpha")
    enc_b = crypto.encrypt("api_key_beta")
    assert enc_a != enc_b


def test_same_input_produces_same_output():
    """Le keystream étant déterministe pour un salt donné, encrypt est stable."""
    plain = "stable_key"
    enc1 = crypto.encrypt(plain)
    enc2 = crypto.encrypt(plain)
    assert enc1 == enc2


# ─── Keystream ────────────────────────────────────────────────────────────────

def test_keystream_lengths_match_request():
    for n in (1, 16, 32, 33, 100, 500):
        ks = crypto._derive_keystream(n)
        assert len(ks) == n


def test_keystream_deterministic_per_salt():
    """Pour le même salt sur disque, _derive_keystream(N) est stable."""
    a = crypto._derive_keystream(64)
    b = crypto._derive_keystream(64)
    assert a == b
