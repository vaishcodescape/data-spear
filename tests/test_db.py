import data_spear.db as db
from data_spear.config import settings


def test_active_dsn_falls_back_to_settings(monkeypatch):
    monkeypatch.setattr(db, "_active_dsn", None)
    # Regression: settings.pg_dsn must exist (README documents PG_DSN).
    assert db.active_dsn() == settings.pg_dsn
    assert db.active_dsn().startswith("postgresql://")


def test_set_active_dsn_overrides(monkeypatch):
    monkeypatch.setattr(db, "_active_dsn", None)
    db.set_active_dsn("postgresql://u:p@h:5/x")
    try:
        assert db.active_dsn() == "postgresql://u:p@h:5/x"
    finally:
        db._active_dsn = None
