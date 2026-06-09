"""
IaC Scanning & Supply Chain Security models for Forail.

A `Scanner` configures one static-analysis tool (ansible-lint, checkov,
pip-audit) with a severity threshold + enforcement. On every launch
attempt the runner resolves the project checkout path, invokes the
tool as a subprocess, parses its JSON output into `ScanFinding` rows
and persists a `ScanResult` summary.
"""

import logging

from django.db import models
from django.utils.translation import gettext_lazy as _

from forail.api.versioning import reverse
from forail.main.models.base import BaseModel, CommonModelNameNotUnique, CreatedModifiedModel

logger = logging.getLogger('forail.main.models.scanner')

__all__ = ['Scanner', 'ScanResult', 'ScanFinding']


# ---------------------------------------------------------------------------
# Pure helpers — exported for unit tests and reused by the runner.
# ---------------------------------------------------------------------------

SEVERITY_INFO = 'info'
SEVERITY_LOW = 'low'
SEVERITY_MEDIUM = 'medium'
SEVERITY_HIGH = 'high'
SEVERITY_CRITICAL = 'critical'

SEVERITY_CHOICES = [
    (SEVERITY_INFO, _('Info')),
    (SEVERITY_LOW, _('Low')),
    (SEVERITY_MEDIUM, _('Medium')),
    (SEVERITY_HIGH, _('High')),
    (SEVERITY_CRITICAL, _('Critical')),
]

SEVERITY_ORDER = {
    SEVERITY_INFO: 0,
    SEVERITY_LOW: 1,
    SEVERITY_MEDIUM: 2,
    SEVERITY_HIGH: 3,
    SEVERITY_CRITICAL: 4,
}

ENFORCEMENT_WARN = 'warn'
ENFORCEMENT_ENFORCE = 'enforce'

ENFORCEMENT_CHOICES = [
    (ENFORCEMENT_WARN, _('Warn only')),
    (ENFORCEMENT_ENFORCE, _('Enforce — block on findings')),
]

TOOL_ANSIBLE_LINT = 'ansible-lint'
TOOL_CHECKOV = 'checkov'
TOOL_PIP_AUDIT = 'pip-audit'

TOOL_CHOICES = [
    (TOOL_ANSIBLE_LINT, _('ansible-lint')),
    (TOOL_CHECKOV, _('Checkov')),
    (TOOL_PIP_AUDIT, _('pip-audit')),
]

STATUS_OK = 'ok'
STATUS_WARN = 'warn'
STATUS_BLOCKED = 'blocked'
STATUS_ERROR = 'error'
STATUS_TIMEOUT = 'timeout'

STATUS_CHOICES = [
    (STATUS_OK, _('OK')),
    (STATUS_WARN, _('Warn')),
    (STATUS_BLOCKED, _('Blocked')),
    (STATUS_ERROR, _('Error')),
    (STATUS_TIMEOUT, _('Timeout')),
]

APPLIES_TO_CHOICES = ['job_template', 'workflow_job_template', 'ad_hoc_command']


def severity_at_or_above(finding_sev, threshold):
    """Return True if finding_sev is >= threshold on the info<low<medium<high<critical
    ordering. Unknown severities are treated as 'info'."""
    f = SEVERITY_ORDER.get((finding_sev or '').lower(), 0)
    t = SEVERITY_ORDER.get((threshold or '').lower(), 0)
    return f >= t


def effective_enforcement(global_enabled, scanner_enforcement):
    """Combine the global kill switch with per-scanner enforcement.
    Returns 'warn' or 'enforce', or 'none' when globally disabled."""
    if not global_enabled:
        return 'none'
    if scanner_enforcement == ENFORCEMENT_ENFORCE:
        return ENFORCEMENT_ENFORCE
    return ENFORCEMENT_WARN


def aggregate_status(findings, threshold):
    """Aggregate a list of finding dicts (with 'severity') into an
    overall status. No findings → ok. Any finding at/above threshold →
    blocked (caller decides warn vs enforce). Below threshold → warn."""
    if not findings:
        return STATUS_OK
    any_at_threshold = False
    for f in findings:
        sev = f.get('severity') if isinstance(f, dict) else getattr(f, 'severity', None)
        if severity_at_or_above(sev, threshold):
            any_at_threshold = True
            break
    if any_at_threshold:
        return STATUS_BLOCKED
    return STATUS_WARN


def fail_mode_decision(scanner_unavailable, fail_mode):
    """When a scanner subprocess crashes or times out, decide whether to
    allow or deny the launch. Returns 'allow' or 'deny'."""
    if not scanner_unavailable:
        return 'allow'
    return 'allow' if fail_mode == 'allow' else 'deny'


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Scanner(CommonModelNameNotUnique):
    """One configured static-analysis tool that gates launches."""

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
        related_name='scanners',
        help_text=_('If null, the scanner is global across all organizations.'),
    )

    tool = models.CharField(
        max_length=32,
        choices=TOOL_CHOICES,
        default=TOOL_ANSIBLE_LINT,
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Tool-specific configuration: rule excludes, profile, etc.'),
    )

    severity_threshold = models.CharField(
        max_length=16,
        choices=SEVERITY_CHOICES,
        default=SEVERITY_HIGH,
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
        help_text=_('Resource types this scanner gates: '
                    'job_template / workflow_job_template / ad_hoc_command. '
                    'Empty = applies to all.'),
    )

    trigger_count = models.PositiveIntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_status = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text=_('Status of the last scan: ok / warn / blocked / error / timeout.'),
    )

    def get_absolute_url(self, request=None):
        return reverse('api:scanner_detail', kwargs={'pk': self.pk}, request=request)

    def applies_to_resource(self, resource_type):
        if not self.applies_to:
            return True
        return resource_type in self.applies_to

    def __str__(self):
        return f'Scanner({self.name})'


class ScanResult(CreatedModifiedModel):
    """One persisted record per scan run."""

    class Meta:
        app_label = 'main'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=['status', '-created']),
            models.Index(fields=['unified_job', '-created']),
            models.Index(fields=['scanner', '-created']),
        ]

    scanner = models.ForeignKey(
        Scanner,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='results',
    )
    scanner_name = models.CharField(max_length=512, blank=True, default='')

    unified_job = models.ForeignKey(
        'UnifiedJob',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='scan_results',
        help_text=_('Null when the launch was blocked before the job was kept.'),
    )
    unified_job_template = models.ForeignKey(
        'UnifiedJobTemplate',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='scan_results',
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
        related_name='scan_results',
    )

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        db_index=True,
    )
    duration_ms = models.PositiveIntegerField(default=0)
    finding_count = models.PositiveIntegerField(default=0)
    highest_severity = models.CharField(max_length=16, blank=True, default='')
    message = models.TextField(blank=True, default='')
    raw_output = models.TextField(blank=True, default='')

    def get_absolute_url(self, request=None):
        return reverse('api:scan_result_detail', kwargs={'pk': self.pk}, request=request)

    def save(self, *args, **kwargs):
        if self.scanner and not self.scanner_name:
            self.scanner_name = self.scanner.name
        super().save(*args, **kwargs)

    def __str__(self):
        return f'ScanResult #{self.pk} [{self.status}] {self.scanner_name}'


class ScanFinding(BaseModel):
    """One finding from a scan run."""

    class Meta:
        app_label = 'main'
        ordering = ('scan_result', 'id')
        indexes = [
            models.Index(fields=['scan_result', 'severity']),
        ]

    scan_result = models.ForeignKey(
        ScanResult,
        on_delete=models.CASCADE,
        related_name='findings',
    )
    rule_id = models.CharField(max_length=255, blank=True, default='')
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_INFO)
    file_path = models.CharField(max_length=1024, blank=True, default='')
    line = models.PositiveIntegerField(null=True, blank=True)
    message = models.TextField(blank=True, default='')

    def get_absolute_url(self, request=None):
        return reverse('api:scan_finding_detail', kwargs={'pk': self.pk}, request=request)

    def __str__(self):
        return f'ScanFinding #{self.pk} [{self.severity}] {self.rule_id}'
