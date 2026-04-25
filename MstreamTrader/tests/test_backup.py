"""
Tests pytest : backup atomique de la DB SQLite + purge.

Vérifie :
  - create_backup produit un fichier valide (DB lisible)
  - purge_old_backups respecte la rétention par date
  - list_backups trié anti-chronologiquement
  - Backup d'une DB inexistante → None (pas de crash)
"""

import pytest
import sys
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import backup as backup_mod


@pytest.fixture
def tmp_backup_dir(tmp_path):
    """Dossier temporaire pour les backups."""
    d = tmp_path / "backups"
    d.mkdir()
    return d


def test_create_backup_produces_valid_file(tmp_backup_dir):
    """Backup réel : fichier créé + lisible comme DB SQLite."""
    path = backup_mod.create_backup(backup_dir=tmp_backup_dir)
    assert path is not None
    assert path.exists()
    assert path.suffix == ".db"
    # Vérifier que c'est une DB lisible
    conn = sqlite3.connect(str(path))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert len(cur) > 0   # au moins quelques tables
    finally:
        conn.close()


def test_create_backup_returns_none_if_source_missing(tmp_backup_dir, monkeypatch):
    """Si la DB source n'existe pas, retourne None sans crash."""
    fake_path = Path("/tmp/does_not_exist_xyz.db")
    monkeypatch.setattr(backup_mod, "_get_source_db_path", lambda: fake_path)
    result = backup_mod.create_backup(backup_dir=tmp_backup_dir)
    assert result is None


def test_purge_keeps_recent_backups(tmp_backup_dir):
    """Un backup d'aujourd'hui doit rester après purge 7 jours."""
    today = datetime.now().strftime("%Y-%m-%d_%H%M")
    f_recent = tmp_backup_dir / f"mstream_trader_{today}.db"
    f_recent.write_bytes(b"fake")
    removed = backup_mod.purge_old_backups(tmp_backup_dir, retention_days=7)
    assert removed == 0
    assert f_recent.exists()


def test_purge_removes_old_backups(tmp_backup_dir):
    """Un backup vieux de 30 jours doit être supprimé."""
    old_dt = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d_%H%M")
    f_old = tmp_backup_dir / f"mstream_trader_{old_dt}.db"
    f_old.write_bytes(b"fake")
    removed = backup_mod.purge_old_backups(tmp_backup_dir, retention_days=7)
    assert removed == 1
    assert not f_old.exists()


def test_purge_skips_malformed_filenames(tmp_backup_dir):
    """Fichiers au nom inattendu ne crashent pas la purge."""
    f_bad = tmp_backup_dir / "mstream_trader_bogus.db"
    f_bad.write_bytes(b"x")
    # Doit passer sans crash et ne pas le supprimer
    removed = backup_mod.purge_old_backups(tmp_backup_dir, retention_days=7)
    assert removed == 0
    assert f_bad.exists()


def test_list_backups_sorted_recent_first(tmp_backup_dir):
    older = tmp_backup_dir / "mstream_trader_2024-01-01_0000.db"
    newer = tmp_backup_dir / "mstream_trader_2026-01-01_0000.db"
    older.write_bytes(b"x")
    newer.write_bytes(b"x")
    files = backup_mod.list_backups(tmp_backup_dir)
    assert len(files) == 2
    assert files[0].name == newer.name


def test_list_backups_empty_dir(tmp_path):
    """Dossier inexistant → liste vide, pas de crash."""
    inexistant = tmp_path / "no_such_dir"
    assert backup_mod.list_backups(inexistant) == []


def test_restore_refuses_inexistant_backup(tmp_path):
    """Restore refuse si le backup n'existe pas."""
    fake = tmp_path / "no.db"
    assert backup_mod.restore_from_backup(fake) is False


def test_restore_refuses_corrupt_backup(tmp_path, monkeypatch):
    """Backup non-SQLite valide → refus, DB cible non touchée."""
    bad = tmp_path / "fake.db"
    bad.write_bytes(b"not a real sqlite database content")
    target = tmp_path / "target.db"
    target.write_bytes(b"original")
    monkeypatch.setattr(backup_mod, "_get_source_db_path", lambda: target)
    ok = backup_mod.restore_from_backup(bad, confirm_overwrite=True)
    assert ok is False
    # La cible originale n'a PAS été touchée (sécurité avant écrasement)
    assert target.read_bytes() == b"original"


def test_restore_refuses_overwrite_without_confirm(tmp_path, monkeypatch):
    """Sans confirm_overwrite=True, refus si DB cible existe."""
    backup = tmp_path / "valid_backup.db"
    src = sqlite3.connect(str(backup))
    src.execute("CREATE TABLE marker (id INTEGER)")
    src.execute("INSERT INTO marker VALUES (42)")
    src.commit()
    src.close()
    target = tmp_path / "target.db"
    target.write_bytes(b"existing target db")
    monkeypatch.setattr(backup_mod, "_get_source_db_path", lambda: target)
    ok = backup_mod.restore_from_backup(backup)   # confirm_overwrite=False par défaut
    assert ok is False
    assert target.read_bytes() == b"existing target db"


def test_restore_roundtrip_atomic(tmp_path, monkeypatch):
    """Crée un backup, modifie la DB, restaure depuis le backup → marker retrouvé."""
    target = tmp_path / "target.db"
    monkeypatch.setattr(backup_mod, "_get_source_db_path", lambda: target)

    # 1. Créer DB initiale avec un marker
    conn = sqlite3.connect(str(target))
    conn.execute("CREATE TABLE marker (val TEXT)")
    conn.execute("INSERT INTO marker VALUES ('original')")
    conn.commit()
    conn.close()

    # 2. Backup
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_path = backup_mod.create_backup(backup_dir=backup_dir)
    assert backup_path is not None and backup_path.exists()

    # 3. Modifier la DB (simule corruption / mauvaise écriture)
    conn = sqlite3.connect(str(target))
    conn.execute("UPDATE marker SET val = 'corrupted'")
    conn.commit()
    conn.close()

    # 4. Restore depuis backup
    ok = backup_mod.restore_from_backup(backup_path, confirm_overwrite=True)
    assert ok is True

    # 5. Vérifier que la valeur 'original' est revenue
    conn = sqlite3.connect(str(target))
    val = conn.execute("SELECT val FROM marker").fetchone()[0]
    conn.close()
    assert val == "original"


def test_restore_keeps_safety_copy_for_rollback(tmp_path, monkeypatch):
    """Après une restauration réussie, une safety copy doit exister pour rollback."""
    target = tmp_path / "target.db"
    monkeypatch.setattr(backup_mod, "_get_source_db_path", lambda: target)

    conn = sqlite3.connect(str(target))
    conn.execute("CREATE TABLE m (v TEXT)")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_path = backup_mod.create_backup(backup_dir=backup_dir)

    backup_mod.restore_from_backup(backup_path, confirm_overwrite=True)
    safety_copies = list(target.parent.glob(f"{target.name}.before_restore_*"))
    assert len(safety_copies) >= 1


def test_create_backup_and_purge_combo(tmp_backup_dir):
    """Le helper combiné crée + purge en un appel."""
    # Pré-remplir avec un backup expiré
    old_dt = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d_%H%M")
    (tmp_backup_dir / f"mstream_trader_{old_dt}.db").write_bytes(b"fake")
    result = backup_mod.create_backup_and_purge(tmp_backup_dir, retention_days=7)
    assert result is not None and result.exists()
    # L'ancien doit avoir été purgé
    remaining = backup_mod.list_backups(tmp_backup_dir)
    assert all("2024" not in f.name for f in remaining)
    assert any(f == result for f in remaining)
