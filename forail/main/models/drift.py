"""
Drift Detection models for Forail.

Captures host fact snapshots after each job run, compares them to detect
configuration drift, and provides alerting when drift exceeds thresholds.
"""

import logging

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import now

from forail.api.versioning import reverse
from forail.main.models.base import CommonModelNameNotUnique

logger = logging.getLogger('forail.main.models.drift')

__all__ = ['HostFactSnapshot', 'DriftDetection', 'DriftAlertRule', 'DriftAlert']


class HostFactSnapshot(models.Model):
    """
    Point-in-time capture of ansible_facts for a single host.

    Created automatically after each job run that uses fact caching.
    Only stored when the facts hash differs from the previous snapshot
    (i.e. something actually changed).
    """

    class Meta:
        app_label = 'main'
        ordering = ('-captured_at',)
        indexes = [
            models.Index(fields=['host', '-captured_at']),
            models.Index(fields=['job', 'host']),
        ]

    host = models.ForeignKey(
        'Host',
        on_delete=models.CASCADE,
        related_name='fact_snapshots',
    )
    job = models.ForeignKey(
        'Job',
        null=True,
        on_delete=models.SET_NULL,
        related_name='fact_snapshots',
    )
    inventory = models.ForeignKey(
        'Inventory',
        null=True,
        on_delete=models.SET_NULL,
        related_name='fact_snapshots',
    )
    organization = models.ForeignKey(
        'Organization',
        null=True,
        on_delete=models.SET_NULL,
    )

    captured_at = models.DateTimeField(auto_now_add=True, db_index=True)

    facts = models.JSONField(
        default=dict,
        help_text=_('Full ansible_facts dictionary at capture time.'),
    )
    facts_hash = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        help_text=_('SHA-256 hash of sorted JSON facts for quick equality check.'),
    )

    def get_absolute_url(self, request=None):
        return reverse('api:fact_snapshot_detail', kwargs={'pk': self.pk}, request=request)

    def __str__(self):
        return f'Snapshot #{self.pk} for {self.host_id} at {self.captured_at}'


class DriftDetection(models.Model):
    """
    A single detected configuration change between two consecutive snapshots.

    Created automatically by the detect_drift Celery task when a new snapshot
    differs from the previous one.
    """

    CATEGORY_CHOICES = [
        ('packages', _('Packages')),
        ('services', _('Services')),
        ('users_groups', _('Users & Groups')),
        ('network', _('Network / Ports')),
        ('mounts', _('Mounts / Filesystems')),
        ('kernel', _('Kernel Parameters')),
        ('other', _('Other')),
    ]

    SEVERITY_CHOICES = [
        ('low', _('Low')),
        ('medium', _('Medium')),
        ('high', _('High')),
        ('critical', _('Critical')),
    ]

    class Meta:
        app_label = 'main'
        ordering = ('-detected_at',)
        indexes = [
            models.Index(fields=['host', '-detected_at']),
            models.Index(fields=['-detected_at']),
            models.Index(fields=['category']),
            models.Index(fields=['severity']),
        ]

    host = models.ForeignKey(
        'Host',
        on_delete=models.CASCADE,
        related_name='drift_detections',
    )
    inventory = models.ForeignKey(
        'Inventory',
        null=True,
        on_delete=models.SET_NULL,
    )
    organization = models.ForeignKey(
        'Organization',
        null=True,
        on_delete=models.SET_NULL,
    )

    snapshot_before = models.ForeignKey(
        HostFactSnapshot,
        null=True,
        on_delete=models.SET_NULL,
        related_name='drifts_before',
    )
    snapshot_after = models.ForeignKey(
        HostFactSnapshot,
        on_delete=models.CASCADE,
        related_name='drifts_after',
    )

    detected_at = models.DateTimeField(auto_now_add=True, db_index=True)

    job = models.ForeignKey(
        'Job',
        null=True,
        on_delete=models.SET_NULL,
        related_name='drift_detections',
    )

    category = models.CharField(
        max_length=32,
        choices=CATEGORY_CHOICES,
        default='other',
    )
    severity = models.CharField(
        max_length=16,
        choices=SEVERITY_CHOICES,
        default='low',
    )
    fact_path = models.CharField(
        max_length=512,
        help_text=_('Dot-delimited path to the changed fact, e.g. "ansible_pkg_mgr".'),
    )
    summary = models.CharField(max_length=1024, blank=True, default='')
    detail = models.JSONField(
        default=dict,
        help_text=_('Structured diff: {before, after, diff_type}.'),
    )

    acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        'auth.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    def get_absolute_url(self, request=None):
        return reverse('api:drift_detection_detail', kwargs={'pk': self.pk}, request=request)

    def __str__(self):
        return f'Drift #{self.pk} [{self.category}/{self.severity}] {self.fact_path}'


class DriftAlertRule(CommonModelNameNotUnique):
    """
    User-defined rule for alerting when drift exceeds a threshold.

    Evaluates drift detections within a time window and sends notifications
    when the count exceeds the configured threshold.
    """

    class Meta:
        app_label = 'main'
        unique_together = ('organization', 'name')
        ordering = ('name',)

    organization = models.ForeignKey(
        'Organization',
        blank=False,
        null=True,
        on_delete=models.CASCADE,
        related_name='drift_alert_rules',
    )

    enabled = models.BooleanField(default=True)

    # Filtering scope
    inventory = models.ForeignKey(
        'Inventory',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    host_filter = models.CharField(
        max_length=512,
        blank=True,
        default='',
        help_text=_('Host name pattern (fnmatch). Empty = all hosts.'),
    )
    categories = models.JSONField(
        default=list,
        blank=True,
        help_text=_('List of drift categories to match. Empty = all.'),
    )
    severity_min = models.CharField(
        max_length=16,
        choices=DriftDetection.SEVERITY_CHOICES,
        default='medium',
    )

    # Threshold
    threshold_count = models.PositiveIntegerField(
        default=1,
        help_text=_('Minimum drift items to trigger alert.'),
    )
    threshold_window_minutes = models.PositiveIntegerField(
        default=60,
        help_text=_('Time window in minutes to count drift items.'),
    )

    # Action
    notification_template = models.ForeignKey(
        'NotificationTemplate',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # Tracking
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    trigger_count = models.PositiveIntegerField(default=0)
    cooldown_minutes = models.PositiveIntegerField(
        default=30,
        help_text=_('Minimum minutes between alerts from this rule.'),
    )

    def get_absolute_url(self, request=None):
        return reverse('api:drift_alert_rule_detail', kwargs={'pk': self.pk}, request=request)

    def is_in_cooldown(self):
        if not self.last_triggered_at or self.cooldown_minutes <= 0:
            return False
        elapsed = (now() - self.last_triggered_at).total_seconds() / 60
        return elapsed < self.cooldown_minutes

    def record_trigger(self):
        self.last_triggered_at = now()
        self.trigger_count = models.F('trigger_count') + 1
        self.save(update_fields=['last_triggered_at', 'trigger_count'])

    def __str__(self):
        return f'{self.name}'


class DriftAlert(models.Model):
    """
    Immutable record of a triggered drift alert.

    Created when a DriftAlertRule threshold is met.
    """

    class Meta:
        app_label = 'main'
        ordering = ('-created',)

    NOTIFICATION_STATUS_CHOICES = [
        ('pending', _('Pending')),
        ('sent', _('Sent')),
        ('failed', _('Failed')),
    ]

    created = models.DateTimeField(auto_now_add=True, db_index=True)

    alert_rule = models.ForeignKey(
        DriftAlertRule,
        null=True,
        on_delete=models.SET_NULL,
        related_name='alerts',
    )
    alert_rule_name = models.CharField(max_length=512, blank=True, default='')

    host = models.ForeignKey(
        'Host',
        null=True,
        on_delete=models.SET_NULL,
    )
    organization = models.ForeignKey(
        'Organization',
        null=True,
        on_delete=models.SET_NULL,
    )

    drift_count = models.PositiveIntegerField(default=0)
    summary = models.TextField(blank=True, default='')

    notification_status = models.CharField(
        max_length=20,
        choices=NOTIFICATION_STATUS_CHOICES,
        default='pending',
    )
    notification_error = models.TextField(blank=True, default='')

    def get_absolute_url(self, request=None):
        return reverse('api:drift_alert_detail', kwargs={'pk': self.pk}, request=request)

    def save(self, *args, **kwargs):
        if self.alert_rule and not self.alert_rule_name:
            self.alert_rule_name = self.alert_rule.name
        super().save(*args, **kwargs)

    def __str__(self):
        return f'DriftAlert #{self.pk} [{self.notification_status}] {self.alert_rule_name}'
