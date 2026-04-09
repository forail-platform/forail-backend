"""Celery tasks for Multi-Tenancy v1."""

import logging

from celery import shared_task

logger = logging.getLogger('forge.main.tasks.tenancy')


@shared_task
def recalculate_tenant_usage_all():
    """Walk all tenant orgs and refresh their TenantUsage counters."""
    from forge.main.models import Organization
    from forge.main.tenancy.usage import recalculate_tenant_usage

    for org in Organization.objects.filter(is_tenant_root=True):
        try:
            recalculate_tenant_usage(org)
        except Exception:  # pylint: disable=broad-except
            logger.exception('recalculate_tenant_usage failed for org %s', org.pk)
