"""Celery tasks for Multi-Tenancy v1."""

import logging

from celery import shared_task

logger = logging.getLogger('forail.main.tasks.tenancy')


@shared_task
def recalculate_tenant_usage_all():
    """Walk all tenant orgs and refresh their TenantUsage counters."""
    from forail.main.models import Organization
    from forail.main.tenancy.usage import recalculate_tenant_usage

    for org in Organization.objects.filter(is_tenant_root=True):
        try:
            recalculate_tenant_usage(org)
        except Exception:  # pylint: disable=broad-except
            logger.exception('recalculate_tenant_usage failed for org %s', org.pk)


@shared_task
def ensure_all_tenant_queues():
    """Declare Celery queues for all tenant orgs (idempotent).

    Runs on beat schedule so that newly provisioned tenants get their
    queues declared even if the provisioning hook failed.
    """
    from django.conf import settings
    if not getattr(settings, 'TENANCY_ENABLED', False):
        return
    if not getattr(settings, 'TENANCY_DEDICATED_QUEUES_ENABLED', False):
        return

    from forail.main.models import Organization
    from forail.main.tenancy.queues import ensure_tenant_queue_exists

    for org_id in Organization.objects.filter(is_tenant_root=True).values_list('pk', flat=True):
        try:
            ensure_tenant_queue_exists(org_id)
        except Exception:  # pylint: disable=broad-except
            logger.exception('ensure_tenant_queue_exists failed for org %s', org_id)
