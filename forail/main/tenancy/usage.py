"""Recalculate tenant usage counters (Celery beat target)."""

import logging

from django.utils.timezone import now as tz_now

logger = logging.getLogger('forail.main.tenancy.usage')


def recalculate_tenant_usage(org):
    """Recompute hosts_count, storage_mb_used, and reconcile
    concurrent_jobs_count for a single tenant Organization."""
    from forail.main.models import Host, UnifiedJob
    from forail.main.models.tenancy import TenantUsage

    usage, _created = TenantUsage.objects.get_or_create(organization=org)

    try:
        hosts_count = Host.objects.filter(inventory__organization=org).count()
    except Exception:  # pylint: disable=broad-except
        logger.exception('hosts_count recompute failed for org %s', org.pk)
        hosts_count = usage.hosts_count

    # v1: storage walk is not implemented; leave 0 / untouched.
    # TODO(v2): sum project checkout sizes on disk.
    storage_mb = usage.storage_mb_used or 0

    try:
        running = UnifiedJob.objects.filter(
            organization=org,
            status__in=['running', 'pending', 'waiting'],
        ).count()
    except Exception:  # pylint: disable=broad-except
        logger.exception('running jobs reconcile failed for org %s', org.pk)
        running = usage.concurrent_jobs_count

    usage.hosts_count = hosts_count
    usage.storage_mb_used = storage_mb
    usage.concurrent_jobs_count = running
    usage.last_recalculated_at = tz_now()
    usage.save()
    return usage
