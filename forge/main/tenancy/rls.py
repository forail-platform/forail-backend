"""Row-Level Security helpers for Multi-Tenancy v2.

Provides functions to set/clear the ``forge.current_tenant_id`` Postgres
session variable and to generate the SQL for RLS policy management.
"""

import logging

from django.db import connection as default_connection

logger = logging.getLogger('forge.main.tenancy.rls')


def set_tenant_id(org_id, conn=None):
    """Set ``forge.current_tenant_id`` as a LOCAL session variable.

    ``SET LOCAL`` scopes the value to the current transaction, which
    Django wraps around each request when ``ATOMIC_REQUESTS=True``.
    If the connection is not in a transaction, falls back to ``SET``.

    Args:
        org_id: The Organization PK to scope queries to.  Pass ``None``
                or ``''`` to clear (all rows visible).
        conn:   Optional DB connection.  Defaults to ``django.db.connection``.
    """
    if conn is None:
        conn = default_connection
    value = str(int(org_id)) if org_id else ''
    try:
        with conn.cursor() as cursor:
            if conn.in_atomic_block:
                cursor.execute("SET LOCAL forge.current_tenant_id = %s", [value])
            else:
                cursor.execute("SET forge.current_tenant_id = %s", [value])
    except Exception:
        logger.exception('Failed to SET forge.current_tenant_id=%s', value)
        raise


def clear_tenant_id(conn=None):
    """Reset ``forge.current_tenant_id`` to empty string (all rows visible)."""
    if conn is None:
        conn = default_connection
    try:
        with conn.cursor() as cursor:
            if conn.in_atomic_block:
                cursor.execute("SET LOCAL forge.current_tenant_id = ''")
            else:
                cursor.execute("SET forge.current_tenant_id = ''")
    except Exception:
        logger.debug('Failed to clear forge.current_tenant_id', exc_info=True)


def get_current_tenant_id(conn=None):
    """Read the current ``forge.current_tenant_id`` session variable.

    Returns the string value or ``''`` if unset.
    """
    if conn is None:
        conn = default_connection
    with conn.cursor() as cursor:
        cursor.execute("SELECT current_setting('forge.current_tenant_id', true)")
        row = cursor.fetchone()
    return (row[0] or '') if row else ''
