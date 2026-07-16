"""Multi-Tenancy v2: extend RLS coverage to main_eventlog.

needtofix M4 — ``EventLog`` carries its own ``organization_id`` but was
omitted from the original RLS policy set (0206). Add the policy here.

Idempotent by construction: the CREATE is preceded by DROP POLICY IF EXISTS,
so this converges whether or not 0206 already created the policy (a fresh
install runs 0206 with main_eventlog already in RLS_TABLES_DIRECT).
"""

from django.db import migrations

from forail.main.tenancy.helpers import build_rls_policy_sql


_TABLE = 'main_eventlog'


def _forward_sql():
    create, drop = build_rls_policy_sql(_TABLE, 'organization_id')
    return '\n'.join([
        f'ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;',
        f'ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;',
        drop,      # drop first so re-create is safe on fresh installs
        create,
    ])


def _reverse_sql():
    _, drop = build_rls_policy_sql(_TABLE, 'organization_id')
    return '\n'.join([
        drop,
        f'ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;',
    ])


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0208_driftalertrule_audit_fields'),
    ]

    operations = [
        migrations.RunSQL(sql=_forward_sql(), reverse_sql=_reverse_sql()),
    ]
