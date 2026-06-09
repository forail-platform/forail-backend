"""Periodic observability tasks.

Populate gauges that can't be incremented at event time (active job count
is inherently a snapshot query).
"""

import logging

logger = logging.getLogger('forail.main.tasks.observability')


def update_active_jobs_gauge():
    """Count jobs currently in pending/waiting/running and publish a gauge.

    Safe to call when OpenTelemetry is not initialized — ``set_active_jobs``
    is a no-op in that case.
    """
    try:
        from forail.main.observability.metrics import set_active_jobs
        from forail.main.models import UnifiedJob
        count = UnifiedJob.objects.filter(
            status__in=['pending', 'waiting', 'running'],
        ).count()
        set_active_jobs(count)
    except Exception as e:  # pylint: disable=broad-except
        logger.debug('update_active_jobs_gauge skipped: %s', e)


# Celery-style wrapper, registered lazily from celery_conf.
try:
    from celery import shared_task

    @shared_task
    def update_active_jobs_gauge_task():  # pragma: no cover
        update_active_jobs_gauge()
except Exception:  # pylint: disable=broad-except
    # Celery may not be available at collectstatic time — that's fine.
    pass
