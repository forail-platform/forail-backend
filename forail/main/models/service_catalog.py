"""
Self-Service Portal models for Forail.

ServiceCatalogItem wraps a JobTemplate or WorkflowJobTemplate with
portal-friendly metadata. ServiceRequest tracks an end-user's request
through its lifecycle (pending_approval -> approved/rejected ->
running -> successful/failed/canceled).
"""

import logging

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import now

from forail.api.versioning import reverse
from forail.main.models.base import CommonModelNameNotUnique, CreatedModifiedModel

logger = logging.getLogger('forail.main.models.service_catalog')

__all__ = ['ServiceCatalogItem', 'ServiceRequest']


class ServiceCatalogItem(CommonModelNameNotUnique):
    """A curated portal entry that wraps an existing JT or WFJT."""

    class Meta:
        app_label = 'main'
        unique_together = ('organization', 'name')
        ordering = ('category', 'name')
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['enabled']),
        ]

    organization = models.ForeignKey(
        'Organization',
        null=True,
        on_delete=models.CASCADE,
        related_name='service_catalog_items',
    )
    icon = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text=_('Lucide icon name shown in the portal card.'),
    )
    category = models.CharField(
        max_length=128,
        blank=True,
        default='',
        db_index=True,
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text=_('Free-form tags for filtering.'),
    )

    job_template = models.ForeignKey(
        'JobTemplate',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='service_catalog_items',
    )
    workflow_job_template = models.ForeignKey(
        'WorkflowJobTemplate',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='service_catalog_items',
    )

    requires_approval = models.BooleanField(default=False)
    approver_team = models.ForeignKey(
        'Team',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approvable_service_catalog_items',
        help_text=_('Team allowed to approve requests. If null, falls back to org admins.'),
    )

    enabled = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if bool(self.job_template) == bool(self.workflow_job_template):
            raise ValidationError(
                _('Exactly one of job_template or workflow_job_template must be set.')
            )

    @property
    def underlying_template(self):
        return self.job_template or self.workflow_job_template

    @property
    def is_workflow(self):
        return self.workflow_job_template_id is not None

    def get_absolute_url(self, request=None):
        return reverse('api:service_catalog_item_detail', kwargs={'pk': self.pk}, request=request)

    def __str__(self):
        return self.name


class ServiceRequest(CreatedModifiedModel):
    """A user's request to launch a catalog item, with optional approval."""

    STATUS_CHOICES = [
        ('pending_approval', _('Pending Approval')),
        ('approved', _('Approved')),
        ('rejected', _('Rejected')),
        ('running', _('Running')),
        ('successful', _('Successful')),
        ('failed', _('Failed')),
        ('canceled', _('Canceled')),
    ]

    TERMINAL_STATUSES = ('rejected', 'successful', 'failed', 'canceled')

    class Meta:
        app_label = 'main'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['requested_by', '-created']),
            models.Index(fields=['catalog_item', '-created']),
        ]

    catalog_item = models.ForeignKey(
        ServiceCatalogItem,
        on_delete=models.CASCADE,
        related_name='requests',
    )
    requested_by = models.ForeignKey(
        'auth.User',
        null=True,
        on_delete=models.SET_NULL,
        related_name='service_requests',
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending_approval',
        db_index=True,
    )

    extra_vars = models.JSONField(default=dict, blank=True)
    node_survey_data = models.JSONField(default=dict, blank=True)
    justification = models.TextField(blank=True, default='')

    approved_by = models.ForeignKey(
        'auth.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_service_requests',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')

    unified_job = models.ForeignKey(
        'UnifiedJob',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='service_requests',
    )

    def get_absolute_url(self, request=None):
        return reverse('api:service_request_detail', kwargs={'pk': self.pk}, request=request)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def submit(self):
        """Initial submission. Auto-approves and launches if no approval needed."""
        if self.catalog_item.requires_approval:
            self.status = 'pending_approval'
            self.save(update_fields=['status', 'modified'])
        else:
            # auto-approve and launch
            self.status = 'approved'
            self.approved_at = now()
            self.save(update_fields=['status', 'approved_at', 'modified'])
            self._launch()
        return self

    def can_user_approve(self, user):
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        team = self.catalog_item.approver_team
        if team is not None:
            return team.member_role.members.filter(pk=user.pk).exists()
        org = self.catalog_item.organization
        if org is None:
            return False
        return org.admin_role.members.filter(pk=user.pk).exists()

    def approve(self, user):
        if self.status != 'pending_approval':
            raise ValidationError(_('Only pending requests can be approved.'))
        if not self.can_user_approve(user):
            raise ValidationError(_('User is not allowed to approve this request.'))
        self.approved_by = user
        self.approved_at = now()
        self.status = 'approved'
        self.save(update_fields=['approved_by', 'approved_at', 'status', 'modified'])
        self._launch()
        return self

    def reject(self, user, reason=''):
        if self.status != 'pending_approval':
            raise ValidationError(_('Only pending requests can be rejected.'))
        if not self.can_user_approve(user):
            raise ValidationError(_('User is not allowed to reject this request.'))
        self.approved_by = user
        self.approved_at = now()
        self.rejection_reason = reason or ''
        self.status = 'rejected'
        self.save(update_fields=[
            'approved_by', 'approved_at', 'rejection_reason', 'status', 'modified',
        ])
        return self

    def _launch(self):
        """Launch the underlying JT/WFJT and link the resulting UnifiedJob."""
        template = self.catalog_item.underlying_template
        if template is None:
            self.status = 'failed'
            self.save(update_fields=['status', 'modified'])
            return None

        kwargs = {
            'extra_vars': self.extra_vars or {},
            '_eager_fields': {'launch_type': 'manual', 'created_by': self.requested_by},
        }
        if self.catalog_item.is_workflow and self.node_survey_data:
            kwargs['node_survey_data'] = self.node_survey_data

        try:
            new_job = template.create_unified_job(**kwargs)
        except TypeError:
            # node_survey_data not supported on this template type
            kwargs.pop('node_survey_data', None)
            new_job = template.create_unified_job(**kwargs)

        if new_job is None:
            self.status = 'failed'
            self.save(update_fields=['status', 'modified'])
            return None

        self.unified_job = new_job
        self.status = 'running'
        self.save(update_fields=['unified_job', 'status', 'modified'])
        try:
            new_job.signal_start()
        except Exception:
            logger.exception('Failed to start unified job for service request %s', self.pk)
        return new_job

    def sync_status_from_job(self):
        """Called by the post-run signal hook to mirror UJ terminal status."""
        if self.status in self.TERMINAL_STATUSES:
            return
        if self.unified_job is None:
            return
        uj_status = self.unified_job.status
        mapping = {
            'successful': 'successful',
            'failed': 'failed',
            'error': 'failed',
            'canceled': 'canceled',
        }
        if uj_status in mapping:
            self.status = mapping[uj_status]
            self.save(update_fields=['status', 'modified'])

    def __str__(self):
        return f'ServiceRequest #{self.pk} [{self.status}] {self.catalog_item_id}'


# ----------------------------------------------------------------------
# Status propagation: when a UnifiedJob enters a terminal state, mirror
# it onto any linked ServiceRequest. Connected via post_save so both
# regular jobs and workflow jobs are covered without touching task code.
# ----------------------------------------------------------------------

from django.db.models.signals import post_save  # noqa: E402
from django.dispatch import receiver  # noqa: E402


@receiver(post_save, sender=None)
def _service_request_sync_on_uj_save(sender, instance, **kwargs):  # pragma: no cover - signal
    if sender is None:
        return
    # Only react to UnifiedJob subclasses
    try:
        from forail.main.models.unified_jobs import UnifiedJob
    except Exception:
        return
    if not isinstance(instance, UnifiedJob):
        return
    if instance.status not in ('successful', 'failed', 'error', 'canceled'):
        return
    try:
        for sr in ServiceRequest.objects.filter(unified_job=instance).exclude(status__in=ServiceRequest.TERMINAL_STATUSES):
            sr.sync_status_from_job()
    except Exception:
        logger.exception('Failed to sync service request status from UJ %s', getattr(instance, 'pk', None))


# Connect the receiver to the generic post_save and filter inside the handler.
post_save.connect(_service_request_sync_on_uj_save)
