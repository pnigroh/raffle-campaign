"""
Test the sequence-reset logic against an in-memory model.

We don't need a real Postgres for the unit test — we test the *SQL emitter*
that walks Django's models and produces the SETVAL statements.
"""
import pytest
from scripts.reset_postgres_sequences import build_setval_statements


def test_emits_setval_for_model_with_id_column():
    statements = build_setval_statements(
        tables=[
            {"name": "campaigns_campaign", "pk_column": "id"},
            {"name": "campaigns_submission", "pk_column": "id"},
        ]
    )
    joined = "\n".join(statements)
    assert "campaigns_campaign_id_seq" in joined
    assert "campaigns_submission_id_seq" in joined
    # Each statement should use COALESCE so empty tables stay at 1.
    assert "COALESCE" in joined


def test_skips_tables_without_serial_pk():
    statements = build_setval_statements(
        tables=[
            {"name": "django_session", "pk_column": "session_key"},
            {"name": "campaigns_campaign", "pk_column": "id"},
        ]
    )
    joined = "\n".join(statements)
    assert "django_session" not in joined
    assert "campaigns_campaign_id_seq" in joined
