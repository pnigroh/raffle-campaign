"""Verify settings.DATABASES respects DATABASE_URL env var."""
import importlib
import os
import sys


def _purge_settings():
    """Remove cached settings module (and its package) so the next import is fresh."""
    for key in ("raffle_project.settings", "raffle_project"):
        sys.modules.pop(key, None)


def test_sqlite_default_when_no_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _purge_settings()
    from raffle_project import settings

    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"


def test_postgres_url_is_parsed(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://raffleuser:rafflepass@db.local:5432/raffledb",
    )
    _purge_settings()
    from raffle_project import settings

    db = settings.DATABASES["default"]
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert db["NAME"] == "raffledb"
    assert db["USER"] == "raffleuser"
    assert db["HOST"] == "db.local"
    assert db["PORT"] == 5432
