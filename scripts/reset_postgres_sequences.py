"""
After `manage.py loaddata`, Postgres sequences for serial primary keys are
NOT advanced past the loaded values. Calling this script emits and executes
SETVAL statements that bump every sequence to MAX(pk) + 1.

Run as:  python -m scripts.reset_postgres_sequences
(via the migration shell script, with Django settings already on the path)
"""
from __future__ import annotations

import sys
from typing import Iterable


def build_setval_statements(tables: Iterable[dict]) -> list[str]:
    """Pure function: list of {name, pk_column} -> list of SQL statements.

    Only emits a SETVAL when pk_column == "id" (Django's BigAutoField default).
    Non-serial PKs (e.g. session_key) get skipped because they don't have a
    sequence to reset.
    """
    statements = []
    for table in tables:
        if table["pk_column"] != "id":
            continue
        seq_name = f"{table['name']}_id_seq"
        # COALESCE handles empty tables: MAX returns NULL, COALESCE makes it 1.
        statements.append(
            f"SELECT setval('{seq_name}', "
            f"COALESCE((SELECT MAX(id) FROM {table['name']}), 1), "
            f"(SELECT MAX(id) IS NOT NULL FROM {table['name']}));"
        )
    return statements


def main() -> int:
    import django

    django.setup()
    from django.apps import apps
    from django.db import connection

    tables = []
    for model in apps.get_models():
        pk = model._meta.pk
        # AutoField / BigAutoField have a sequence; everything else does not.
        if pk.get_internal_type() not in ("AutoField", "BigAutoField"):
            continue
        tables.append(
            {"name": model._meta.db_table, "pk_column": pk.column}
        )

    statements = build_setval_statements(tables)
    print(f"Resetting {len(statements)} sequences...")
    with connection.cursor() as cur:
        for stmt in statements:
            print(f"  {stmt}")
            cur.execute(stmt)
    print("Done.")
    return 0


if __name__ == "__main__":
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "raffle_project.settings")
    sys.exit(main())
