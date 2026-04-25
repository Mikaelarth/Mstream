"""
MstreamTrader - Obfuscation des secrets au repos
=================================================

Chiffrement symétrique stream (XOR) avec clé dérivée PBKDF2-SHA256
pour protéger les clés API stockées dans la base SQLite.

Niveau de protection :
    - Empêche la lecture directe via extraction de la DB seule
    - Résiste à l'inspection casuelle / snapshot / backup
    - N'est PAS de la crypto forte : un attaquant ayant accès au code + DB + fichier salt
      peut déchiffrer. Considérer comme une obfuscation renforcée, pas un chiffrement E2E.

Recommandations additionnelles pour l'utilisateur :
    - Créer la clé Binance SANS permission de withdraw
    - Activer la whitelist IP côté Binance
    - Ne pas exécuter l'app sur un téléphone rooté sans protection supplémentaire

Le salt est stocké dans un fichier séparé (.mstream_salt) hors de la DB.
Compromettre les clés nécessite d'avoir simultanément : la DB + le salt + le code.
"""

import os
import base64
import hashlib
from pathlib import Path

from core import paths


# Fichier salt stocké à côté de la DB (mais séparé du fichier SQLite)
# Sur Android, dans le storage privé de l'app — survit aux redémarrages
_SALT_FILE = paths.SALT_FILE

# Constante liée au binaire de l'app
_APP_SECRET = b"MstreamTrader_v1_local_at_rest_obfuscation_layer"

# Préfixe marquant une valeur chiffrée en DB (permet compat arrière avec valeurs en clair)
ENC_PREFIX = "enc:"


def _get_or_create_salt() -> bytes:
    """Charge le salt existant ou en crée un nouveau (32 octets aléatoires)."""
    if _SALT_FILE.exists():
        try:
            salt = _SALT_FILE.read_bytes()
            if len(salt) >= 32:
                return salt
        except OSError:
            pass
    # Générer un nouveau salt
    salt = os.urandom(32)
    try:
        _SALT_FILE.write_bytes(salt)
        # Restreindre les droits sur POSIX (Android)
        try:
            os.chmod(_SALT_FILE, 0o600)
        except OSError:
            pass
    except OSError:
        # En cas d'échec d'écriture (FS read-only), utiliser un salt déterministe
        # sécurité réduite mais ne casse pas l'app
        salt = hashlib.sha256(_APP_SECRET + b"_fallback").digest()
    return salt


def _derive_keystream(length: int) -> bytes:
    """
    Dérive un keystream de `length` octets via PBKDF2-SHA256 puis extension
    par chaînage de SHA256 sur le bloc précédent.
    """
    salt = _get_or_create_salt()
    # Bloc de base : 32 octets
    base = hashlib.pbkdf2_hmac("sha256", _APP_SECRET, salt, 100_000, dklen=32)

    if length <= 32:
        return base[:length]

    # Extension par chaînage de SHA256 — équivalent d'un DRBG très simple
    stream = bytearray(base)
    block  = base
    while len(stream) < length:
        block = hashlib.sha256(block + salt).digest()
        stream.extend(block)
    return bytes(stream[:length])


def encrypt(plaintext: str) -> str:
    """
    Chiffre une chaîne UTF-8. Retourne 'enc:' + base64(ciphertext).
    Une chaîne vide retourne "".
    """
    if not plaintext:
        return ""
    data       = plaintext.encode("utf-8")
    keystream  = _derive_keystream(len(data))
    ciphertext = bytes(a ^ b for a, b in zip(data, keystream))
    return ENC_PREFIX + base64.b64encode(ciphertext).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """
    Déchiffre une chaîne produite par encrypt().
    Si la chaîne n'a pas le préfixe 'enc:', elle est retournée telle quelle
    (compatibilité avec les anciennes valeurs stockées en clair).
    """
    if not ciphertext:
        return ""
    if not ciphertext.startswith(ENC_PREFIX):
        return ciphertext  # valeur héritée, non chiffrée
    try:
        data      = base64.b64decode(ciphertext[len(ENC_PREFIX):])
        keystream = _derive_keystream(len(data))
        return bytes(a ^ b for a, b in zip(data, keystream)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def is_encrypted(value: str) -> bool:
    """Retourne True si la valeur est déjà chiffrée."""
    return bool(value) and value.startswith(ENC_PREFIX)
