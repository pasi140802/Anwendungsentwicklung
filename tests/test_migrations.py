"""Migrationen und Datenmodell stimmen überein (Schema kommt nur aus Alembic)."""

from alembic import command
from alembic.config import Config

from tests.conftest import ALEMBIC_INI


def test_models_match_migrations():
    # Wirft eine Ausnahme, wenn die Modelle Änderungen ohne Migration enthalten.
    command.check(Config(ALEMBIC_INI))
