"""Pure-Python helpers for Multi-Tenancy v1.

No Django imports — importable by standalone tests via importlib.
"""

import re
from datetime import datetime, time, timezone


# Quota kind constants
QUOTA_KIND_CONCURRENT_JOBS = 'concurrent_jobs'
QUOTA_KIND_DAILY_LAUNCHES = 'daily_launches'
QUOTA_KIND_HOSTS = 'hosts'
QUOTA_KIND_STORAGE_MB = 'storage_mb'

QUOTA_KINDS = (
    QUOTA_KIND_CONCURRENT_JOBS,
    QUOTA_KIND_DAILY_LAUNCHES,
    QUOTA_KIND_HOSTS,
    QUOTA_KIND_STORAGE_MB,
)

DECISION_ALLOWED = 'allowed'
DECISION_BLOCKED = 'blocked'

_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def check_quota_value(current, limit):
    """Return True if current < limit. None or 0 limit means unlimited."""
    if limit is None or limit == 0:
        return True
    try:
        return int(current) < int(limit)
    except (TypeError, ValueError):
        return True


def is_window_expired(window_start, now):
    """Return True if the window_start is on a different UTC calendar day
    than now. If window_start is None, consider the window expired."""
    if window_start is None:
        return True
    ws = window_start
    n = now
    # Normalize to UTC date
    if hasattr(ws, 'astimezone'):
        try:
            ws = ws.astimezone(timezone.utc)
        except Exception:
            pass
    if hasattr(n, 'astimezone'):
        try:
            n = n.astimezone(timezone.utc)
        except Exception:
            pass
    return ws.date() != n.date()


def reset_daily_window(now):
    """Return (top_of_day_utc, 0) tuple. Caller stores both."""
    if hasattr(now, 'astimezone'):
        try:
            now = now.astimezone(timezone.utc)
        except Exception:
            pass
    top = datetime.combine(now.date(), time(0, 0, 0), tzinfo=timezone.utc)
    return (top, 0)


_QUOTA_KIND_LABELS = {
    QUOTA_KIND_CONCURRENT_JOBS: 'Concurrent jobs',
    QUOTA_KIND_DAILY_LAUNCHES: 'Daily launches',
    QUOTA_KIND_HOSTS: 'Hosts',
    QUOTA_KIND_STORAGE_MB: 'Storage (MB)',
}


def format_quota_message(kind, current, limit):
    label = _QUOTA_KIND_LABELS.get(kind, str(kind))
    lim = 'unlimited' if (limit is None or limit == 0) else int(limit)
    return f'{label} quota exceeded ({int(current)}/{lim})'


def normalize_host(host):
    """Lowercase, strip whitespace, strip :port suffix, strip trailing dot."""
    if host is None:
        return ''
    s = str(host).strip().lower()
    if not s:
        return ''
    # Strip :port (only for non-bracketed hosts)
    if ':' in s and not s.startswith('['):
        s = s.split(':', 1)[0]
    # Strip trailing dot
    if s.endswith('.'):
        s = s[:-1]
    return s


def is_valid_hex_color(s):
    if not s or not isinstance(s, str):
        return False
    return bool(_HEX_COLOR_RE.match(s))


# ---------------------------------------------------------------------------
# Strict Isolation — v2
# ---------------------------------------------------------------------------

# Paths that are always exempt from cross-tenant checks (public, auth, meta).
ISOLATION_EXEMPT_PATH_PREFIXES = (
    '/api/v2/config/',
    '/api/v2/ping/',
    '/api/v2/me/',
    '/api/v2/auth/',
    '/api/v2/tokens/',
    '/api/v2/branding/',
    '/api/v2/tenants/',
    '/api/v2/tenant_quota_events/',
    '/api/v2/tenant_isolation_events/',
    '/api/login/',
    '/sso/',
)


def should_exempt_isolation(path):
    """Return True if the request path should skip isolation checks."""
    if not path:
        return True
    for prefix in ISOLATION_EXEMPT_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def make_isolation_decision(user_org_strict, global_strict_enabled, is_cross_tenant):
    """Determine the isolation action for a request.

    Returns a tuple ``(should_block, should_audit)``.

    - If the request is not cross-tenant: ``(False, False)``
    - If cross-tenant and strict on both levels: ``(True, True)``
    - If cross-tenant but either strict flag is off: ``(False, True)``
    """
    if not is_cross_tenant:
        return (False, False)
    # Always audit cross-tenant access.
    should_block = bool(user_org_strict and global_strict_enabled)
    return (should_block, True)


# ---------------------------------------------------------------------------
# Row-Level Security (RLS) — v2
# ---------------------------------------------------------------------------

# Each entry is (db_table, org_column).  ``org_column`` is the column name
# that references Organization.id — directly ('organization_id') for most
# tables or via a subquery for indirect relationships.
#
# Tables with nullable organization_id are included; the RLS policy handles
# NULLs by treating them as "visible to everyone" (no tenant scope).

RLS_TABLES_DIRECT = [
    # Core resources
    ('main_inventory', 'organization_id'),
    ('main_credential', 'organization_id'),
    ('main_label', 'organization_id'),
    ('main_executionenvironment', 'organization_id'),
    ('main_team', 'organization_id'),
    ('main_notificationtemplate', 'organization_id'),
    ('main_oauth2application', 'organization_id'),
    # Jobs
    ('main_unifiedjobtemplate', 'organization_id'),
    ('main_unifiedjob', 'organization_id'),
    # EDA
    ('main_eventrule', 'organization_id'),
    ('main_outboundwebhook', 'organization_id'),
    # Drift detection
    ('main_hostfactsnapshot', 'organization_id'),
    ('main_driftdetection', 'organization_id'),
    ('main_driftalertrule', 'organization_id'),
    ('main_driftalert', 'organization_id'),
    # Compliance
    ('main_policy', 'organization_id'),
    ('main_policydecision', 'organization_id'),
    ('main_scanner', 'organization_id'),
    ('main_scanresult', 'organization_id'),
    # Service catalog
    ('main_servicecatalogitem', 'organization_id'),
    # Audit
    ('main_auditevent', 'organization_id'),
]

# Tables where the org relationship is indirect (via FK to another table).
# We handle these with a subquery-based policy, not listed in RLS_TABLES_DIRECT.
RLS_TABLES_INDIRECT = [
    # Host → Inventory → Organization
    ('main_host', 'inventory_id', 'main_inventory', 'organization_id'),
]


def build_rls_policy_sql(table, org_column='organization_id'):
    """Return (create_sql, drop_sql) for a permissive RLS policy.

    The policy allows the row when:
    1. ``organization_id`` matches ``forge.current_tenant_id``, OR
    2. ``organization_id`` IS NULL (global/shared resources), OR
    3. The session variable is empty / unset (no tenant context — backwards
       compatible for non-tenant requests and superusers).
    """
    policy_name = f'tenant_isolation_{table}'
    create = (
        f'CREATE POLICY {policy_name} ON {table} '
        f'AS PERMISSIVE FOR ALL '
        f'USING ('
        f'{org_column} = current_setting(\'forge.current_tenant_id\', true)::int '
        f'OR {org_column} IS NULL '
        f'OR current_setting(\'forge.current_tenant_id\', true) IS NULL '
        f'OR current_setting(\'forge.current_tenant_id\', true) = \'\''
        f');'
    )
    drop = f'DROP POLICY IF EXISTS {policy_name} ON {table};'
    return (create, drop)


def build_rls_policy_sql_indirect(table, fk_column, parent_table, parent_org_column):
    """Return (create_sql, drop_sql) for an indirect RLS policy.

    Uses a subquery to resolve the organization from a parent table.
    """
    policy_name = f'tenant_isolation_{table}'
    create = (
        f'CREATE POLICY {policy_name} ON {table} '
        f'AS PERMISSIVE FOR ALL '
        f'USING ('
        f'{fk_column} IN ('
        f'SELECT id FROM {parent_table} WHERE '
        f'{parent_org_column} = current_setting(\'forge.current_tenant_id\', true)::int '
        f'OR {parent_org_column} IS NULL'
        f') '
        f'OR {fk_column} IS NULL '
        f'OR current_setting(\'forge.current_tenant_id\', true) IS NULL '
        f'OR current_setting(\'forge.current_tenant_id\', true) = \'\''
        f');'
    )
    drop = f'DROP POLICY IF EXISTS {policy_name} ON {table};'
    return (create, drop)


def validate_provisioning_payload(payload):
    """Return a list of error strings; empty list means valid."""
    errors = []
    if not isinstance(payload, dict):
        return ['payload must be an object']

    name = payload.get('name')
    if not name or not str(name).strip():
        errors.append('name is required')

    admin_username = payload.get('admin_username')
    if not admin_username or len(str(admin_username)) < 3:
        errors.append('admin_username must be at least 3 characters')

    admin_email = payload.get('admin_email')
    if not admin_email or '@' not in str(admin_email):
        errors.append('admin_email must be a valid email address')

    admin_password = payload.get('admin_password')
    if not admin_password or len(str(admin_password)) < 8:
        errors.append('admin_password must be at least 8 characters')

    quota = payload.get('quota') or {}
    if not isinstance(quota, dict):
        errors.append('quota must be an object')
        quota = {}
    for q_field in ('max_concurrent_jobs', 'max_daily_launches', 'max_hosts', 'max_storage_mb'):
        if q_field in quota and quota[q_field] is not None:
            v = quota[q_field]
            try:
                iv = int(v)
                if iv < 0:
                    errors.append(f'{q_field} must be >= 0')
            except (TypeError, ValueError):
                errors.append(f'{q_field} must be an integer')

    branding = payload.get('branding') or {}
    if not isinstance(branding, dict):
        errors.append('branding must be an object')
        branding = {}
    for c_field in ('primary_color', 'secondary_color'):
        v = branding.get(c_field)
        if v:
            if not is_valid_hex_color(v):
                errors.append(f'{c_field} must be a valid hex color like #RRGGBB')

    return errors
