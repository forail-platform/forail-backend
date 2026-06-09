"""Multi-Tenancy v2: Row-Level Security policies.

Creates RLS policies on all tenant-scoped tables.  Each policy restricts
row visibility to ``forail.current_tenant_id`` (a session-level GUC set per
request by ``TenantIsolationMiddleware``).

The policies are *permissive* and include a bypass clause: when the session
variable is unset, empty, or NULL, **all rows are visible**.  This keeps
the system fully backwards-compatible when ``TENANCY_RLS_ENABLED=False``
or when no middleware is active (e.g. management commands, Celery workers).

Reversible: the reverse migration drops all policies and disables RLS.
"""

from django.db import migrations

from forail.main.tenancy.helpers import (
    RLS_TABLES_DIRECT,
    RLS_TABLES_INDIRECT,
    build_rls_policy_sql,
    build_rls_policy_sql_indirect,
)


def _build_forward_sql():
    statements = []
    for table, org_col in RLS_TABLES_DIRECT:
        create, _ = build_rls_policy_sql(table, org_col)
        statements.append(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;')
        statements.append(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY;')
        statements.append(create)
    for table, fk_col, parent_table, parent_org_col in RLS_TABLES_INDIRECT:
        create, _ = build_rls_policy_sql_indirect(table, fk_col, parent_table, parent_org_col)
        statements.append(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;')
        statements.append(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY;')
        statements.append(create)
    return '\n'.join(statements)


def _build_reverse_sql():
    statements = []
    for table, org_col in RLS_TABLES_DIRECT:
        _, drop = build_rls_policy_sql(table, org_col)
        statements.append(drop)
        statements.append(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;')
    for table, fk_col, parent_table, parent_org_col in RLS_TABLES_INDIRECT:
        _, drop = build_rls_policy_sql_indirect(table, fk_col, parent_table, parent_org_col)
        statements.append(drop)
        statements.append(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;')
    return '\n'.join(statements)


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0205_multi_tenancy'),
    ]

    operations = [
        migrations.RunSQL(
            sql=_build_forward_sql(),
            reverse_sql=_build_reverse_sql(),
        ),
    ]
