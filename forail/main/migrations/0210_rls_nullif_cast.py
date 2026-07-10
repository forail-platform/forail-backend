"""Multi-Tenancy v2: recreate RLS policies with a NULLIF-guarded cast.

needtofix L6 — the original policies cast the raw GUC as
``current_setting(...)::int``, which raises on the empty-string "no tenant
scope" sentinel; Postgres does not guarantee the ``= ''`` guard is evaluated
before the cast. build_rls_policy_sql now emits
``NULLIF(current_setting(...), '')::int`` instead. Recreate every policy so
existing installs pick up the robust form.

Idempotent: each policy is dropped (IF EXISTS) then recreated, for both
direct and indirect tables, so this converges on fresh and existing DBs.
"""

from django.db import migrations

from forail.main.tenancy.helpers import (
    RLS_TABLES_DIRECT,
    RLS_TABLES_INDIRECT,
    build_rls_policy_sql,
    build_rls_policy_sql_indirect,
)


def _rebuild_sql():
    statements = []
    for table, org_col in RLS_TABLES_DIRECT:
        create, drop = build_rls_policy_sql(table, org_col)
        statements.append(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;')
        statements.append(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY;')
        statements.append(drop)
        statements.append(create)
    for table, fk_col, parent_table, parent_org_col in RLS_TABLES_INDIRECT:
        create, drop = build_rls_policy_sql_indirect(table, fk_col, parent_table, parent_org_col)
        statements.append(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;')
        statements.append(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY;')
        statements.append(drop)
        statements.append(create)
    return '\n'.join(statements)


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0209_rls_eventlog'),
    ]

    operations = [
        # Forward and reverse both rebuild from the current builder; the reverse
        # is a no-op distinction here (policies are recreated either way), which
        # is acceptable because the builder is the single source of truth.
        migrations.RunSQL(sql=_rebuild_sql(), reverse_sql=_rebuild_sql()),
    ]
