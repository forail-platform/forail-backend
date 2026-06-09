"""
Event-Driven Automation (EDA) models for Forail.

Provides webhook-based event routing with user-defined rules (conditions + actions)
for automated job/workflow launching and notification dispatch.
"""

import logging
import secrets
from hashlib import sha1, sha256

import hmac as hmac_mod

from django.db import models
from django.utils.encoding import force_bytes
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import now

from ansible_base.lib.utils.models import prevent_search

from forail.api.versioning import reverse
from forail.main.models.base import CommonModelNameNotUnique, CreatedModifiedModel

logger = logging.getLogger('forail.main.models.eda')

__all__ = ['EventRule', 'EventLog', 'OutboundWebhook']


class EventRule(CommonModelNameNotUnique):
    """
    A user-defined rule that maps inbound webhook events to automated actions.

    When a webhook is received at /api/v2/eda_webhooks/<webhook_path>/, the rule
    engine evaluates conditions (Jinja2 expressions) against the payload and, if
    all conditions match, executes the configured actions (launch job template,
    launch workflow, send notification).
    """

    SOURCE_TYPE_CHOICES = [
        ('webhook_generic', _('Generic Webhook')),
        ('webhook_github', _('GitHub')),
        ('webhook_gitlab', _('GitLab')),
        ('alertmanager', _('Alertmanager')),
        ('pagerduty', _('PagerDuty')),
        ('datadog', _('Datadog')),
        ('cloudwatch', _('CloudWatch')),
    ]

    ACTION_TYPE_CHOICES = [
        ('launch_job_template', _('Launch Job Template')),
        ('launch_workflow', _('Launch Workflow')),
        ('send_notification', _('Send Notification')),
    ]

    class Meta:
        app_label = 'main'
        unique_together = ('organization', 'name')
        ordering = ('name',)

    organization = models.ForeignKey(
        'Organization',
        blank=False,
        null=True,
        on_delete=models.CASCADE,
        related_name='event_rules',
    )

    enabled = models.BooleanField(
        default=True,
        help_text=_('Whether this rule is actively processing incoming webhooks.'),
    )

    source_type = models.CharField(
        max_length=32,
        choices=SOURCE_TYPE_CHOICES,
        default='webhook_generic',
        help_text=_('Type of webhook source. Determines signature verification method.'),
    )

    webhook_path = models.SlugField(
        max_length=128,
        unique=True,
        help_text=_('Unique URL path segment for the webhook endpoint: /api/v2/eda_webhooks/<webhook_path>/'),
    )

    webhook_key = prevent_search(models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text=_('Shared secret for HMAC signature verification of incoming webhooks.'),
    ))

    conditions = models.JSONField(
        default=list,
        blank=True,
        help_text=_(
            'List of conditions to evaluate. Each condition is a dict with '
            '"jinja2_expression" (string) and optional "description" (string). '
            'All conditions must match (AND logic). '
            'Example: [{"jinja2_expression": "event.action == \'opened\'", "description": "PR opened"}]'
        ),
    )

    actions = models.JSONField(
        default=list,
        help_text=_(
            'List of actions to execute when conditions match. Each action is a dict with '
            '"action_type" (launch_job_template|launch_workflow|send_notification), '
            '"target_id" (int), optional "extra_vars" (dict), and optional "description" (string). '
            'Example: [{"action_type": "launch_job_template", "target_id": 5, "extra_vars": {}}]'
        ),
    )

    throttle_seconds = models.PositiveIntegerField(
        default=0,
        help_text=_('Minimum seconds between rule firings. 0 means no throttling.'),
    )

    last_fired_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        help_text=_('Timestamp of the last time this rule fired an action.'),
    )

    fire_count = models.PositiveIntegerField(
        default=0,
        editable=False,
        help_text=_('Total number of times this rule has fired actions.'),
    )

    def get_absolute_url(self, request=None):
        return reverse('api:event_rule_detail', kwargs={'pk': self.pk}, request=request)

    def rotate_webhook_key(self):
        self.webhook_key = secrets.token_urlsafe(38)

    def save(self, *args, **kwargs):
        if not self.webhook_key:
            self.rotate_webhook_key()
        super().save(*args, **kwargs)

    def check_signature(self, request_body, headers):
        """
        Verify the HMAC signature of an incoming webhook request.

        Returns True if valid, raises ValueError with reason if not.
        """
        if not self.webhook_key:
            raise ValueError("No webhook key configured")

        if self.source_type == 'webhook_github':
            return self._check_github_signature(request_body, headers)
        elif self.source_type == 'webhook_gitlab':
            return self._check_gitlab_signature(headers)
        else:
            return self._check_generic_signature(request_body, headers)

    def _check_github_signature(self, body, headers):
        header_sig = headers.get('X-Hub-Signature-256') or headers.get('X-Hub-Signature')
        if not header_sig:
            raise ValueError("Missing X-Hub-Signature header")
        if '=' not in header_sig:
            raise ValueError("Invalid signature format")
        hash_alg, signature = header_sig.split('=', 1)
        digestmod = sha256 if hash_alg == 'sha256' else sha1
        mac = hmac_mod.new(force_bytes(self.webhook_key), msg=force_bytes(body), digestmod=digestmod)
        if not hmac_mod.compare_digest(force_bytes(mac.hexdigest()), force_bytes(signature)):
            raise ValueError("Signature mismatch")
        return True

    def _check_gitlab_signature(self, headers):
        token = headers.get('X-Gitlab-Token', '')
        if not hmac_mod.compare_digest(force_bytes(self.webhook_key), force_bytes(token)):
            raise ValueError("Token mismatch")
        return True

    def _check_generic_signature(self, body, headers):
        header_sig = headers.get('X-Forail-Signature', '')
        if not header_sig:
            raise ValueError("Missing X-Forail-Signature header")
        if '=' in header_sig:
            _, signature = header_sig.split('=', 1)
        else:
            signature = header_sig
        mac = hmac_mod.new(force_bytes(self.webhook_key), msg=force_bytes(body), digestmod=sha256)
        if not hmac_mod.compare_digest(force_bytes(mac.hexdigest()), force_bytes(signature)):
            raise ValueError("Signature mismatch")
        return True

    def is_throttled(self):
        if self.throttle_seconds <= 0 or not self.last_fired_at:
            return False
        elapsed = (now() - self.last_fired_at).total_seconds()
        return elapsed < self.throttle_seconds

    def record_firing(self):
        self.last_fired_at = now()
        self.fire_count = models.F('fire_count') + 1
        self.save(update_fields=['last_fired_at', 'fire_count'])

    def __str__(self):
        return f'{self.name} ({self.source_type})'


class EventLog(models.Model):
    """
    Immutable log of incoming webhook events and rule evaluation outcomes.

    Each received webhook creates one EventLog entry tracking the full lifecycle:
    received -> conditions evaluated -> action fired (or not).
    """

    STATUS_CHOICES = [
        ('received', _('Received')),
        ('matched', _('Matched')),
        ('unmatched', _('Unmatched')),
        ('throttled', _('Throttled')),
        ('action_fired', _('Action Fired')),
        ('action_failed', _('Action Failed')),
        ('error', _('Error')),
        ('signature_failed', _('Signature Failed')),
    ]

    class Meta:
        app_label = 'main'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=['-created']),
            models.Index(fields=['event_rule', '-created']),
            models.Index(fields=['status']),
        ]

    created = models.DateTimeField(auto_now_add=True, db_index=True)

    event_rule = models.ForeignKey(
        EventRule,
        null=True,
        on_delete=models.SET_NULL,
        related_name='event_logs',
    )
    event_rule_name = models.CharField(
        max_length=512,
        blank=True,
        default='',
        help_text=_('Denormalized rule name, preserved after rule deletion.'),
    )

    source_type = models.CharField(max_length=32, blank=True, default='')
    source_ip = models.GenericIPAddressField(null=True, blank=True)

    event_type = models.CharField(
        max_length=128,
        blank=True,
        default='',
        help_text=_('Event type from the source, e.g. "push", "pull_request", "alert".'),
    )
    event_guid = models.CharField(
        max_length=256,
        blank=True,
        default='',
        help_text=_('Unique event ID from source for deduplication.'),
    )

    payload = models.JSONField(default=dict, help_text=_('Raw incoming webhook payload.'))
    headers = models.JSONField(default=dict, help_text=_('Relevant HTTP headers.'))

    conditions_matched = models.BooleanField(default=False)
    condition_results = models.JSONField(
        default=list,
        blank=True,
        help_text=_('Detail of each condition evaluation.'),
    )

    actions_triggered = models.JSONField(
        default=list,
        blank=True,
        help_text=_('List of actions that were executed and their results.'),
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='received',
    )
    error_detail = models.TextField(blank=True, default='')

    job_id = models.IntegerField(
        null=True,
        blank=True,
        help_text=_('ID of launched job/workflow, if applicable.'),
    )

    organization = models.ForeignKey(
        'Organization',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='event_logs',
    )

    def get_absolute_url(self, request=None):
        return reverse('api:event_log_detail', kwargs={'pk': self.pk}, request=request)

    def save(self, *args, **kwargs):
        if self.event_rule and not self.event_rule_name:
            self.event_rule_name = self.event_rule.name
        if self.event_rule and not self.organization:
            self.organization = self.event_rule.organization
        if self.event_rule and not self.source_type:
            self.source_type = self.event_rule.source_type
        super().save(*args, **kwargs)

    def __str__(self):
        return f'EventLog #{self.pk} [{self.status}] for {self.event_rule_name}'


class OutboundWebhook(CommonModelNameNotUnique):
    """
    Outbound webhook configuration for pushing job status changes to external systems.

    When a job/workflow reaches a matching status, Forail POSTs a signed JSON payload
    to the configured URL.
    """

    EVENT_CHOICES = [
        ('job.started', _('Job Started')),
        ('job.succeeded', _('Job Succeeded')),
        ('job.failed', _('Job Failed')),
        ('job.canceled', _('Job Canceled')),
        ('workflow.started', _('Workflow Started')),
        ('workflow.succeeded', _('Workflow Succeeded')),
        ('workflow.failed', _('Workflow Failed')),
    ]

    class Meta:
        app_label = 'main'
        unique_together = ('organization', 'name')
        ordering = ('name',)

    organization = models.ForeignKey(
        'Organization',
        blank=False,
        null=True,
        on_delete=models.CASCADE,
        related_name='outbound_webhooks',
    )

    url = models.URLField(
        max_length=1024,
        help_text=_('Target URL to POST job status payloads to.'),
    )

    webhook_key = prevent_search(models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text=_('HMAC secret for signing outbound payloads (X-Forail-Signature header).'),
    ))

    events = models.JSONField(
        default=list,
        help_text=_('List of event types to send, e.g. ["job.succeeded", "job.failed"].'),
    )

    custom_headers = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Additional HTTP headers to include in outbound requests.'),
    )

    enabled = models.BooleanField(default=True)

    ssl_verify = models.BooleanField(
        default=True,
        help_text=_('Verify SSL certificates when sending outbound webhooks.'),
    )

    last_status = models.CharField(
        max_length=20,
        blank=True,
        default='',
        choices=[
            ('success', _('Success')),
            ('failed', _('Failed')),
        ],
    )

    last_sent_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_error = models.TextField(blank=True, default='', editable=False)

    def get_absolute_url(self, request=None):
        return reverse('api:outbound_webhook_detail', kwargs={'pk': self.pk}, request=request)

    def rotate_webhook_key(self):
        self.webhook_key = secrets.token_urlsafe(38)

    def save(self, *args, **kwargs):
        if not self.webhook_key:
            self.rotate_webhook_key()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} -> {self.url}'
