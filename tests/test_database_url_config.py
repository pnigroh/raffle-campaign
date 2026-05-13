"""Verify settings.DATABASES respects DATABASE_URL env var."""
import sys


def _evict_settings_modules(monkeypatch):
    """Evict cached settings modules via monkeypatch so teardown restores them."""
    for name in ("raffle_project.settings", "raffle_project"):
        monkeypatch.delitem(sys.modules, name, raising=False)


def test_sqlite_default_when_no_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _evict_settings_modules(monkeypatch)
    from raffle_project import settings

    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"


def test_postgres_url_is_parsed(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://raffleuser:rafflepass@db.local:5432/raffledb",
    )
    _evict_settings_modules(monkeypatch)
    from raffle_project import settings

    db = settings.DATABASES["default"]
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert db["NAME"] == "raffledb"
    assert db["USER"] == "raffleuser"
    assert db["HOST"] == "db.local"
    assert db["PORT"] == 5432
