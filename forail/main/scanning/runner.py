"""Scanner runner.

For each enabled Scanner whose applies_to matches the unified_job's
resource type, resolve the project checkout path + playbook, invoke
the tool subprocess with a timeout, parse its JSON output into
NormalizedFindings, filter by severity_threshold, persist a ScanResult
plus ScanFinding rows and aggregate into a ScanRunResult.
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field

from django.utils.timezone import now

logger = logging.getLogger('forail.main.scanning.runner')


@dataclass
class ScanRunResult:
    allowed: bool = True
    warn_messages: list = field(default_factory=list)
    block_messages: list = field(default_factory=list)
    results: list = field(default_factory=list)  # ScanResult instances


def _resource_type(unified_job):
    cls_name = type(unified_job).__name__
    if cls_name == 'Job':
        return 'job_template'
    if cls_name == 'WorkflowJob':
        return 'workflow_job_template'
    if cls_name == 'AdHocCommand':
        return 'ad_hoc_command'
    return cls_name.lower()


def _resolve_project_path(unified_job):
    project = getattr(unified_job, 'project', None)
    if project is None:
        return None
    if hasattr(project, 'get_project_path'):
        try:
            p = project.get_project_path()
            if p:
                return p
        except Exception:
            pass
    return getattr(project, 'local_path', None) or None


def _resolve_target(unified_job, resource_type, project_path, tool_name):
    if not project_path:
        return None
    if resource_type == 'workflow_job_template':
        return None
    if resource_type == 'job_template':
        playbook = getattr(unified_job, 'playbook', '') or ''
        if not playbook:
            return None
        return os.path.join(project_path, playbook)
    if resource_type == 'ad_hoc_command':
        if tool_name == 'ansible-lint':
            return None
        return project_path
    return project_path


def _models_q_org(org_id):
    from django.db.models import Q
    if org_id is None:
        return Q(organization__isnull=True)
    return Q(organization_id=org_id) | Q(organization__isnull=True)


def run_scanners_for_launch(unified_job, request=None):
    from django.conf import settings
    from forail.main.models.scanner import (
        Scanner,
        ScanResult,
        ScanFinding,
        severity_at_or_above,
        effective_enforcement,
        aggregate_status,
        fail_mode_decision,
        ENFORCEMENT_ENFORCE,
        STATUS_OK,
        STATUS_WARN,
        STATUS_BLOCKED,
        STATUS_ERROR,
        STATUS_TIMEOUT,
    )
    from forail.main.scanning.tools import get_adapter

    result = ScanRunResult()

    if not getattr(settings, 'SCANNER_ENABLED', False):
        return result

    timeout_s = int(getattr(settings, 'SCANNER_TIMEOUT_S', 120))
    fail_mode = getattr(settings, 'SCANNER_FAIL_MODE', 'allow')
    raw_max = int(getattr(settings, 'SCANNER_RAW_OUTPUT_MAX', 8192))

    resource_type = _resource_type(unified_job)

    template = (getattr(unified_job, 'unified_job_template', None)
                or getattr(unified_job, 'job_template', None))
    org = None
    if template is not None:
        org = getattr(template, 'organization', None)
    if org is None:
        org = getattr(unified_job, 'organization', None)
    org_id = getattr(org, 'id', None) if org else None

    user = getattr(request, 'user', None)

    qs = Scanner.objects.filter(enabled=True)
    qs = qs.filter(_models_q_org(org_id))
    scanners = [s for s in qs if s.applies_to_resource(resource_type)]
    if not scanners:
        return result

    project_path = _resolve_project_path(unified_job)

    from forail.main.observability.tracing import span as _otel_span
    from forail.main.observability import metrics as _otel_metrics

    for scanner in scanners:
        eff = effective_enforcement(True, scanner.enforcement)
        adapter = get_adapter(scanner.tool)
        if adapter is None:
            logger.warning('No adapter for scanner tool %s', scanner.tool)
            continue

        target = _resolve_target(unified_job, resource_type, project_path, scanner.tool)
        if not target:
            continue

        cmd = adapter.build_command(target, scanner.config or {})

        started = time.monotonic()
        status = STATUS_OK
        stdout = ''
        stderr = ''
        returncode = 0
        unavailable = False
        try:
            with _otel_span('forail.scanner.run', tool=getattr(scanner, 'tool', ''),
                            scanner_name=getattr(scanner, 'name', '')):
                proc = subprocess.run(
                    cmd,
                    timeout=timeout_s,
                    capture_output=True,
                    text=True,
                )
            stdout = proc.stdout or ''
            stderr = proc.stderr or ''
            returncode = proc.returncode
        except subprocess.TimeoutExpired as e:
            status = STATUS_TIMEOUT
            unavailable = True
            stderr = f'Scanner timed out after {timeout_s}s: {e}'
        except (FileNotFoundError, OSError) as e:
            status = STATUS_ERROR
            unavailable = True
            stderr = f'Scanner subprocess failed: {e}'
        except Exception as e:  # pylint: disable=broad-except
            status = STATUS_ERROR
            unavailable = True
            stderr = f'Scanner subprocess exception: {e}'

        duration_ms = int((time.monotonic() - started) * 1000)

        findings_raw = []
        if not unavailable:
            try:
                findings_raw = adapter.parse_output(stdout, stderr, returncode) or []
            except Exception as e:  # pylint: disable=broad-except
                logger.warning('Scanner %s parse failed: %s', scanner.name, e)
                status = STATUS_ERROR
                unavailable = True

        # Filter by severity_threshold. Findings below threshold are dropped
        # so audit logs stay focused; aggregation is over what's left.
        threshold = scanner.severity_threshold
        filtered = [f for f in findings_raw if severity_at_or_above(f.severity, threshold)]

        highest = ''
        for f in filtered:
            from forail.main.models.scanner import SEVERITY_ORDER
            if SEVERITY_ORDER.get(f.severity, 0) > SEVERITY_ORDER.get(highest, -1):
                highest = f.severity

        if unavailable:
            _otel_metrics.inc_scan_runs(status)
            decision_kind = fail_mode_decision(True, fail_mode)
            message = stderr[:512] or f'Scanner {scanner.tool} unavailable.'
            sr = ScanResult.objects.create(
                scanner=scanner,
                scanner_name=scanner.name,
                unified_job=unified_job if decision_kind != 'deny' else None,
                unified_job_template=template,
                organization_id=org_id,
                triggered_by=user if user and getattr(user, 'is_authenticated', False) else None,
                status=status,
                duration_ms=duration_ms,
                finding_count=0,
                highest_severity='',
                message=message,
                raw_output=(stdout or stderr)[:raw_max],
            )
            result.results.append(sr)
            Scanner.objects.filter(pk=scanner.pk).update(
                last_run_at=now(),
                last_run_status=status,
            )
            if decision_kind == 'deny':
                result.allowed = False
                result.block_messages.append(f'[{scanner.name}] {message}')
            else:
                result.warn_messages.append(f'[{scanner.name}] {message}')
            continue

        _otel_metrics.inc_scan_runs('ok' if not filtered else 'findings')

        if not filtered:
            sr_status = STATUS_OK
        else:
            agg = aggregate_status(
                [{'severity': f.severity} for f in filtered],
                threshold,
            )
            if agg == STATUS_BLOCKED and eff == ENFORCEMENT_ENFORCE:
                sr_status = STATUS_BLOCKED
            else:
                sr_status = STATUS_WARN

        message = ''
        if filtered:
            first = filtered[0]
            message = f'{len(filtered)} finding(s); first: [{first.severity}] {first.rule_id} {first.message}'[:512]

        sr = ScanResult.objects.create(
            scanner=scanner,
            scanner_name=scanner.name,
            unified_job=unified_job if sr_status != STATUS_BLOCKED else None,
            unified_job_template=template,
            organization_id=org_id,
            triggered_by=user if user and getattr(user, 'is_authenticated', False) else None,
            status=sr_status,
            duration_ms=duration_ms,
            finding_count=len(filtered),
            highest_severity=highest,
            message=message,
            raw_output=(stdout or '')[:raw_max],
        )
        result.results.append(sr)

        for f in filtered:
            ScanFinding.objects.create(
                scan_result=sr,
                rule_id=f.rule_id or '',
                severity=f.severity or 'info',
                file_path=f.file_path or '',
                line=f.line,
                message=f.message or '',
            )

        update_fields = {
            'last_run_at': now(),
            'last_run_status': sr_status,
        }
        if filtered:
            update_fields['trigger_count'] = scanner.trigger_count + 1
        Scanner.objects.filter(pk=scanner.pk).update(**update_fields)

        if sr_status == STATUS_BLOCKED:
            result.allowed = False
            for f in filtered:
                result.block_messages.append(
                    f'[{scanner.name}] {f.rule_id} {f.file_path}:{f.line or ""} {f.message}'[:512]
                )
        elif sr_status == STATUS_WARN and filtered:
            result.warn_messages.append(
                f'[{scanner.name}] {len(filtered)} finding(s), highest={highest}'
            )

    return result
