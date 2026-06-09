"""Multi-Tenancy v1 models for Forail.

Turns an Organization into a Tenant with quotas, branding, and
cross-tenant isolation audit. Pure helpers live in
``forail/main/tenancy/helpers.py`` so standalone tests can import them
without Django.
"""

import logging

from django.db import models
from django.utils.translation import gettext_lazy as _

from forail.api.versioning import reverse
from forail.main.models.base import BaseModel, CreatedModifiedModel

# Re-export pure helpers so ``from forail.main.models.tenancy import ...``
# still works for the rest of the codebase.
from forail.main.tenancy.helpers import (  # noqa: F401
    QUOTA_KIND_CONCURRENT_JOBS,
    QUOTA_KIND_DAILY_LAUNCHES,
    QUOTA_KIND_HOSTS,
    QUOTA_KIND_STORAGE_MB,
    QUOTA_KINDS,
    DECISION_ALLOWED,
    DECISION_BLOCKED,
    check_quota_value,
    is_window_expired,
    reset_daily_window,
    format_quota_message,
    normalize_host,
    is_valid_hex_color,
    validate_provisioning_payload,
)

logger = logging.getLogger('forail.main.models.tenancy')

__all__ = [
    'TenantUsage',
    'TenantQuotaEvent',
    'TenantIsolationEvent',
    'QUOTA_KIND_CONCURRENT_JOBS',
    'QUOTA_KIND_DAILY_LAUNCHES',
    'QUOTA_KIND_HOSTS',
    'QUOTA_KIND_STORAGE_MB',
    'DECISION_ALLOWED',
    'DECISION_BLOCKED',
]


QUOTA_KIND_CHOICES = [
    (QUOTA_KIND_CONCURRENT_JOBS, _('Concurrent jobs')),
    (QUOTA_KIND_DAILY_LAUNCHES, _('Daily launches')),
    (QUOTA_KIND_HOSTS, _('Hosts')),
    (QUOTA_KIND_STORAGE_MB, _('Storage MB')),
]

DECISION_CHOICES = [
    (DECISION_ALLOWED, _('Allowed')),
    (DECISION_BLOCKED, _('Blocked')),
]


class TenantUsage(BaseModel):
    """One row per tenant Organization tracking rolling counters."""

    class Meta:
        app_label = 'main'
        ordering = ('organization',)

    organization = models.OneToOneField(
        'Organization',
        on_delete=models.CASCADE,
        related_name='tenant_usage',
    )
    concurrent_jobs_count = models.PositiveIntegerField(default=0)
    launches_today_count = models.PositiveIntegerField(default=0)
    launches_today_window_start = models.DateTimeField(null=True, blank=True)
    hosts_count = models.PositiveIntegerField(default=0)
    storage_mb_used = models.PositiveIntegerField(default=0)
    last_recalculated_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.launches_today_window_start is None:
            from django.utils.timezone import now as tz_now
            top, zero = reset_daily_window(tz_now())
            self.launches_today_window_start = top
            if not self.launches_today_count:
                self.launches_today_count = zero
        super().save(*args, **kwargs)

    def get_absolute_url(self, request=None):
        return reverse('api:tenant_detail', kwargs={'pk': self.organization_id}, request=request)

    def __str__(self):
        return f'TenantUsage(org={self.organization_id})'


class TenantQuotaEvent(CreatedModifiedModel):
    """One row per quota evaluation (allow or block) for audit trail."""

    class Meta:
        app_label = 'main'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=['organization', '-created']),
            models.Index(fields=['decision', '-created']),
            models.Index(fields=['quota_kind', '-created']),
        ]

    organization = models.ForeignKey(
        'Organization',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tenant_quota_events',
    )
    organization_name = models.CharField(max_length=512, blank=True, default='')
    quota_kind = models.CharField(max_length=32, choices=QUOTA_KIND_CHOICES)
    decision = models.CharField(max_length=16, choices=DECISION_CHOICES)
    current_value = models.PositiveIntegerField(default=0)
    limit_value = models.PositiveIntegerField(null=True, blank=True)
    triggered_by = models.ForeignKey(
        'auth.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tenant_quota_events',
    )
    unified_job_template = models.ForeignKey(
        'UnifiedJobTemplate',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tenant_quota_events',
    )
    message = models.TextField(blank=True, default='')

    def get_absolute_url(self, request=None):
        return reverse('api:tenant_quota_event_detail', kwargs={'pk': self.pk}, request=request)

    def __str__(self):
        return f'TenantQuotaEvent #{self.pk} [{self.decision}] {self.quota_kind}'


class TenantIsolationEvent(CreatedModifiedModel):
    """Audit log of cross-tenant query access. v1: blocked is always False."""

    class Meta:
        app_label = 'main'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=['user', '-created']),
            models.Index(fields=['user_organization', '-created']),
        ]

    user = models.ForeignKey(
        'auth.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tenant_isolation_events',
    )
    user_organization = models.ForeignKey(
        'Organization',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tenant_isolation_events_as_user_org',
    )
    accessed_organization = models.ForeignKey(
        'Organization',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tenant_isolation_events_as_accessed',
    )
    resource_type = models.CharField(max_length=64, blank=True, default='')
    resource_id = models.PositiveIntegerField(null=True, blank=True)
    request_path = models.CharField(max_length=1024, blank=True, default='')
    blocked = models.BooleanField(default=False)

    def get_absolute_url(self, request=None):
        return reverse('api:tenant_isolation_event_detail', kwargs={'pk': self.pk}, request=request)

    def __str__(self):
        return f'TenantIsolationEvent #{self.pk} [{"blocked" if self.blocked else "audit"}]'
