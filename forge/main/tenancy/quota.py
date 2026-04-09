"""Tenant quota gate for launches."""

import logging
from dataclasses import dataclass, field
from typing import List

from django.conf import settings
from django.db import transaction
from django.utils.timezone import now as tz_now

from forge.main.tenancy.helpers import (
    QUOTA_KIND_CONCURRENT_JOBS,
    QUOTA_KIND_DAILY_LAUNCHES,
    QUOTA_KIND_HOSTS,
    QUOTA_KIND_STORAGE_MB,
    DECISION_ALLOWED,
    DECISION_BLOCKED,
    check_quota_value,
    is_window_expired,
    reset_daily_window,
    format_quota_message,
)

logger = logging.getLogger('forge.main.tenancy.quota')


@dataclass
class QuotaResult:
    allowed: bool = True
    reasons: List[str] = field(default_factory=list)
    events: List[object] = field(default_factory=list)


def _get_org(unified_job):
    org = getattr(unified_job, 'organization', None)
    if org is not None:
        return org
    # Fall back via inventory for ad-hoc commands.
    inv = getattr(unified_job, 'inventory', None)
    if inv is not None:
        return getattr(inv, 'organization', None)
    return None


def check_tenant_quota(unified_job, request):
    """Evaluate tenant quotas for a launch. Returns QuotaResult."""
    result = QuotaResult(allowed=True)

    if not bool(getattr(settings, 'TENANCY_ENABLED', False)):
        return result

    org = _get_org(unified_job)
    if org is None or not getattr(org, 'is_tenant_root', False):
        return result

    # Lazy imports to avoid load-order issues.
    from forge.main.models.tenancy import TenantUsage, TenantQuotaEvent

    user = getattr(request, 'user', None) if request is not None else None
    ujt = getattr(unified_job, 'unified_job_template', None)

    with transaction.atomic():
        usage, _created = TenantUsage.objects.select_for_update().get_or_create(organization=org)
        now = tz_now()

        # Daily window rollover
        if is_window_expired(usage.launches_today_window_start, now):
            top, zero = reset_daily_window(now)
            usage.launches_today_window_start = top
            usage.launches_today_count = zero

        checks = [
            (QUOTA_KIND_CONCURRENT_JOBS, int(usage.concurrent_jobs_count or 0), org.tenant_max_concurrent_jobs),
            (QUOTA_KIND_DAILY_LAUNCHES, int(usage.launches_today_count or 0), org.tenant_max_daily_launches),
            (QUOTA_KIND_HOSTS, int(usage.hosts_count or 0), org.tenant_max_hosts),
            (QUOTA_KIND_STORAGE_MB, int(usage.storage_mb_used or 0), org.tenant_max_storage_mb),
        ]

        blocked = False
        for kind, current, limit in checks:
            if not check_quota_value(current, limit):
                msg = format_quota_message(kind, current, limit)
                result.allowed = False
                result.reasons.append(msg)
                try:
                    ev = TenantQuotaEvent.objects.create(
                        organization=org,
                        organization_name=getattr(org, 'name', '') or '',
                        quota_kind=kind,
                        decision=DECISION_BLOCKED,
                        current_value=current,
                        limit_value=limit if limit else None,
                        triggered_by=user if getattr(user, 'is_authenticated', False) else None,
                        unified_job_template=ujt,
                        message=msg,
                    )
                    result.events.append(ev)
                except Exception:  # pylint: disable=broad-except
                    logger.exception('Failed to persist TenantQuotaEvent (blocked)')
                blocked = True
                break

        if not blocked:
            # Increment live counters.
            usage.concurrent_jobs_count = int(usage.concurrent_jobs_count or 0) + 1
            usage.launches_today_count = int(usage.launches_today_count or 0) + 1
            usage.save()

            for kind, current, limit in checks:
                try:
                    ev = TenantQuotaEvent.objects.create(
                        organization=org,
                        organization_name=getattr(org, 'name', '') or '',
                        quota_kind=kind,
                        decision=DECISION_ALLOWED,
                        current_value=current,
                        limit_value=limit if limit else None,
                        triggered_by=user if getattr(user, 'is_authenticated', False) else None,
                        unified_job_template=ujt,
                        message='',
                    )
                    result.events.append(ev)
                except Exception:  # pylint: disable=broad-except
                    logger.exception('Failed to persist TenantQuotaEvent (allowed)')
        else:
            usage.save(update_fields=['launches_today_window_start', 'launches_today_count', 'modified'])

    return result


def on_job_finished(unified_job):
    """Decrement concurrent_jobs_count when a unified job reaches a terminal state."""
    try:
        org = _get_org(unified_job)
        if org is None or not getattr(org, 'is_tenant_root', False):
            return
        from forge.main.models.tenancy import TenantUsage
        with transaction.atomic():
            usage = TenantUsage.objects.select_for_update().filter(organization=org).first()
            if not usage:
                return
            usage.concurrent_jobs_count = max(0, int(usage.concurrent_jobs_count or 0) - 1)
            usage.save(update_fields=['concurrent_jobs_count', 'modified'])
    except Exception:  # pylint: disable=broad-except
        logger.exception('on_job_finished failed')
