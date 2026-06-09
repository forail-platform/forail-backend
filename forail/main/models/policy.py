"""
Policy-as-Code (OPA) models for Forail.

A `Policy` stores a Rego module that is pushed to an OPA sidecar; on
every launch attempt the evaluator builds a context document, calls
OPA, and persists `PolicyDecision` rows for each violation.
"""

import logging

from django.db import models
from django.utils.translation import gettext_lazy as _

from forail.api.versioning import reverse
from forail.main.models.base import CommonModelNameNotUnique, CreatedModifiedModel

logger = logging.getLogger('forail.main.models.policy')

__all__ = ['Policy', 'PolicyDecision']


# Pure helpers — exported for unit tests and reused by the evaluator.

ENFORCEMENT_NONE = 'none'
ENFORCEMENT_WARN = 'warn'
ENFORCEMENT_ENFORCE = 'enforce'

ENFORCEMENT_CHOICES = [
    (ENFORCEMENT_NONE, _('Disabled')),
    (ENFORCEMENT_WARN, _('Warn only')),
    (ENFORCEMENT_ENFORCE, _('Enforce — block on deny')),
]

DECISION_ALLOW = 'allow'
DECISION_WARN = 'warn'
DECISION_DENY = 'deny'

DECISION_CHOICES = [
    (DECISION_ALLOW, _('Allow')),
    (DECISION_WARN, _('Warn')),
    (DECISION_DENY, _('Deny')),
]

APPLIES_TO_CHOICES = ['job_template', 'workflow_job_template', 'ad_hoc_command']


def effective_enforcement(global_enabled, org_enforcement, policy_enforcement):
    """Combine the global kill switch, the org override and the per-policy
    enforcement into a single decision: 'none' / 'warn' / 'enforce'."""
    if not global_enabled:
        return ENFORCEMENT_NONE
    if org_enforcement == ENFORCEMENT_NONE:
        return ENFORCEMENT_NONE
    # warn caps enforce — an org in warn mode never blocks
    if org_enforcement == ENFORCEMENT_WARN:
        return ENFORCEMENT_WARN
    # org is enforce → policy decides between warn / enforce
    return policy_enforcement


def fail_mode_decision(opa_unavailable, fail_mode):
    """When OPA is unreachable, decide whether to allow or deny the launch.
    Returns 'allow' or 'deny'."""
    if not opa_unavailable:
        return 'allow'
    return 'allow' if fail_mode == 'allow' else 'deny'


class Policy(CommonModelNameNotUnique):
    """A Rego module that gates launches."""

    class Meta:
        app_label = 'main'
        unique_together = ('organization', 'name')
        ordering = ('name',)
        indexes = [
            models.Index(fields=['enabled']),
        ]

    organization = models.ForeignKey(
        'Organization',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='policies',
        help_text=_('If null, the policy is global across all organizations.'),
    )

    rego_module = models.TextField(
        blank=True,
        default='',
        help_text=_('Full Rego source. Pushed to OPA on save.'),
    )
    package_path = models.CharField(
        max_length=255,
        default='forail.launch',
        help_text=_('OPA data path that will be queried, e.g. "forail.launch".'),
    )

    enforcement = models.CharField(
        max_length=16,
        choices=ENFORCEMENT_CHOICES,
        default=ENFORCEMENT_ENFORCE,
    )
    enabled = models.BooleanField(default=True)

    applies_to = models.JSONField(
        default=list,
        blank=True,
        help_text=_('Resource types this policy gates: '
                    'job_template / workflow_job_template / ad_hoc_command. '
                    'Empty = applies to all.'),
    )

    trigger_count = models.PositiveIntegerField(default=0)
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    last_evaluated_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text=_('Status of the last push to OPA: ok / failed / pending.'),
    )

    def get_absolute_url(self, request=None):
        return reverse('api:policy_detail', kwargs={'pk': self.pk}, request=request)

    def applies_to_resource(self, resource_type):
        if not self.applies_to:
            return True
        return resource_type in self.applies_to

    def __str__(self):
        return f'Policy({self.name})'


class PolicyDecision(CreatedModifiedModel):
    """One persisted record per policy hit (warn or deny)."""

    class Meta:
        app_label = 'main'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=['decision', '-created']),
            models.Index(fields=['unified_job', '-created']),
            models.Index(fields=['policy', '-created']),
        ]

    policy = models.ForeignKey(
        Policy,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='decisions',
    )
    policy_name = models.CharField(max_length=512, blank=True, default='')

    decision = models.CharField(
        max_length=8,
        choices=DECISION_CHOICES,
        db_index=True,
    )

    unified_job = models.ForeignKey(
        'UnifiedJob',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='policy_decisions',
        help_text=_('Null when the launch was blocked before the job was kept.'),
    )
    unified_job_template = models.ForeignKey(
        'UnifiedJobTemplate',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='policy_decisions',
    )

    organization = models.ForeignKey(
        'Organization',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    triggered_by = models.ForeignKey(
        'auth.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='policy_decisions',
    )

    message = models.TextField(blank=True, default='')
    context = models.JSONField(default=dict, blank=True)

    def get_absolute_url(self, request=None):
        return reverse('api:policy_decision_detail', kwargs={'pk': self.pk}, request=request)

    def save(self, *args, **kwargs):
        if self.policy and not self.policy_name:
            self.policy_name = self.policy.name
        super().save(*args, **kwargs)

    def __str__(self):
        return f'PolicyDecision #{self.pk} [{self.decision}] {self.policy_name}'
