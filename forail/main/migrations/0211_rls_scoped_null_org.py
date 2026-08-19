"""Multi-Tenancy v2: stop treating every NULL organization as globally shared.

Codex M6 — the policies emitted ``OR organization_id IS NULL`` for every table,
so a row saved without an organization was readable by every tenant. Whether a
NULL organization means "shared with the platform" is now decided per table by
``RLS_GLOBAL_NULL_ORG_TABLES``; the rest are scoped strictly.

This changes visibility for existing rows: on a tenant-scoped request, rows with
no organization in a strictly-scoped table stop being returned. They are not
deleted and remain visible to superusers and to any request without a tenant
context. If a resource "disappears" for a tenant after this migration, the fix
is to assign its organization -- not to add its table to the global list.

Idempotent: each policy is dropped (IF EXISTS) then recreated, for both direct
and indirect tables, so this converges on fresh and existing databases.
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
        ('main', '0210_rls_nullif_cast'),
    ]

    operations = [
        migrations.RunSQL(sql=_rebuild_sql(), reverse_sql=migrations.RunSQL.noop),
    ]
