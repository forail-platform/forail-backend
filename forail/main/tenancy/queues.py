"""Per-tenant Celery queue routing — Multi-Tenancy v2.

When ``TENANCY_DEDICATED_QUEUES_ENABLED`` is True, jobs belonging to a
tenant Organization are routed to a dedicated ``tenant-{org_id}`` queue.
Workers can subscribe to specific tenant queues for fair scheduling.

If the feature is disabled, or the job has no tenant org, the default
queue is used (no routing override).
"""

import logging

from django.conf import settings

from forail.main.tenancy.helpers import tenant_queue_name

logger = logging.getLogger('forail.main.tenancy.queues')


def get_queue_for_org(org):
    """Return the queue name for a tenant org, or ``None`` for default.

    Returns ``None`` when:
    - ``TENANCY_DEDICATED_QUEUES_ENABLED`` is False
    - ``TENANCY_ENABLED`` is False
    - ``org`` is None or not a tenant root
    """
    if not getattr(settings, 'TENANCY_ENABLED', False):
        return None
    if not getattr(settings, 'TENANCY_DEDICATED_QUEUES_ENABLED', False):
        return None
    if org is None or not getattr(org, 'is_tenant_root', False):
        return None
    name = tenant_queue_name(org.pk)
    return name or None


def get_queue_for_job(unified_job):
    """Resolve the tenant queue for a unified job, or ``None`` for default."""
    org = getattr(unified_job, 'organization', None)
    if org is None:
        inv = getattr(unified_job, 'inventory', None)
        if inv is not None:
            org = getattr(inv, 'organization', None)
    return get_queue_for_org(org)


def ensure_tenant_queue_exists(org_id):
    """Declare a tenant queue in the broker (idempotent).

    Uses Kombu to declare the queue so that it exists before a worker
    subscribes to it.  Safe to call multiple times.
    """
    name = tenant_queue_name(org_id)
    if not name:
        return
    try:
        from celery import current_app
        with current_app.connection_or_acquire() as conn:
            from kombu import Queue
            q = Queue(name, channel=conn.default_channel)
            q.declare()
            logger.debug('Declared tenant queue: %s', name)
    except Exception:
        logger.debug('Failed to declare tenant queue %s', name, exc_info=True)


class TenantQueueRouter:
    """Celery task router that directs tenant jobs to dedicated queues.

    Configured via ``CELERY_TASK_ROUTES`` in celery_conf.py.
    Only applies to task names that match known job-runner tasks.
    """

    # Task names that should be routed per-tenant.
    ROUTABLE_TASKS = {
        'awx.main.tasks.system.handle_work_success',
        'awx.main.tasks.system.handle_work_error',
        'awx.main.scheduler.tasks.run_task_manager',
    }

    def route_for_task(self, task, args=None, kwargs=None):
        """Return a dict with ``queue`` key, or ``None`` for default routing."""
        if not getattr(settings, 'TENANCY_ENABLED', False):
            return None
        if not getattr(settings, 'TENANCY_DEDICATED_QUEUES_ENABLED', False):
            return None
        # For now, routing is handled at launch time in the view layer
        # via get_queue_for_job().  This router is a placeholder for
        # future expansion where Celery-internal tasks could also be
        # routed per-tenant.
        return None
