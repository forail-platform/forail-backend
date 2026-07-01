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


# Registered on the beat schedule (celery_conf). Must use the forail dispatch
# @task decorator — the dispatcher's periodic scheduler rejects any scheduled
# task that isn't decorated with it ("not decorated with @task()"), which would
# crash the dispatcher and stall all job processing.
from forail.main.dispatch import get_task_queuename  # noqa: E402
from forail.main.dispatch.publish import task  # noqa: E402


@task(queue=get_task_queuename)
def update_active_jobs_gauge_task():  # pragma: no cover
    update_active_jobs_gauge()
