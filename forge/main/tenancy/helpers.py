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
