"""Build the launch context, ask OPA, persist PolicyDecision rows."""

import logging
from dataclasses import dataclass, field
from typing import Any

from django.utils.timezone import now

logger = logging.getLogger('forge.main.policy.evaluator')


@dataclass
class PolicyDecisionResult:
    allowed: bool = True
    warn_messages: list = field(default_factory=list)
    deny_messages: list = field(default_factory=list)
    decisions: list = field(default_factory=list)  # PolicyDecision instances


def _resource_type(unified_job):
    cls_name = type(unified_job).__name__
    if cls_name == 'Job':
        return 'job_template'
    if cls_name == 'WorkflowJob':
        return 'workflow_job_template'
    if cls_name == 'AdHocCommand':
        return 'ad_hoc_command'
    return cls_name.lower()


def build_launch_context(unified_job, request=None):
    """Build the JSON document handed to OPA as `input.*`."""
    user = getattr(request, 'user', None)
    template = getattr(unified_job, 'unified_job_template', None) or getattr(unified_job, 'job_template', None)

    org = None
    if template is not None:
        org = getattr(template, 'organization', None)
    if org is None:
        org = getattr(unified_job, 'organization', None)

    inventory = getattr(unified_job, 'inventory', None)
    creds = []
    try:
        for c in unified_job.credentials.all():
            creds.append({
                'id': c.id,
                'name': c.name,
                'kind': getattr(c.credential_type, 'kind', '') if c.credential_type else '',
            })
    except Exception:
        pass

    extra_vars = {}
    try:
        if hasattr(unified_job, 'extra_vars_dict'):
            extra_vars = unified_job.extra_vars_dict or {}
    except Exception:
        pass

    return {
        'resource_type': _resource_type(unified_job),
        'resource_id': getattr(unified_job, 'id', None),
        'resource_name': getattr(unified_job, 'name', '') or '',
        'organization_id': getattr(org, 'id', None) if org else None,
        'organization_name': getattr(org, 'name', '') if org else '',
        'user': {
            'id': getattr(user, 'id', None) if user else None,
            'username': getattr(user, 'username', '') if user else '',
            'is_superuser': bool(getattr(user, 'is_superuser', False)) if user else False,
        },
        'extra_vars': extra_vars if isinstance(extra_vars, dict) else {},
        'inventory': {
            'id': getattr(inventory, 'id', None) if inventory else None,
            'name': getattr(inventory, 'name', '') if inventory else '',
            'kind': getattr(inventory, 'kind', '') if inventory else '',
        },
        'credentials': creds,
        'playbook': getattr(unified_job, 'playbook', '') or '',
        'now_iso': now().isoformat(),
        'client_ip': getattr(request, 'META', {}).get('REMOTE_ADDR', '') if request else '',
    }


def evaluate_launch(unified_job, request=None):
    """Evaluate all enabled policies that apply to this launch.

    Returns a PolicyDecisionResult with the aggregate verdict and persisted
    PolicyDecision rows.
    """
    from django.conf import settings
    from forge.main.models.policy import (
        Policy,
        PolicyDecision,
        ENFORCEMENT_NONE,
        ENFORCEMENT_WARN,
        ENFORCEMENT_ENFORCE,
        DECISION_DENY,
        DECISION_WARN,
        effective_enforcement,
        fail_mode_decision,
    )
    from forge.main.policy.opa_client import evaluate as opa_evaluate, parse_decision, OPAUnavailable

    result = PolicyDecisionResult()

    if not getattr(settings, 'OPA_ENABLED', False):
        return result

    context = build_launch_context(unified_job, request)
    resource_type = context['resource_type']
    org_id = context['organization_id']

    org_enforcement = ENFORCEMENT_NONE
    if org_id:
        try:
            from forge.main.models.organization import Organization
            org_enforcement = Organization.objects.values_list(
                'policy_enforcement', flat=True,
            ).get(pk=org_id) or ENFORCEMENT_NONE
        except Exception:
            pass

    if org_enforcement == ENFORCEMENT_NONE:
        return result

    qs = Policy.objects.filter(enabled=True)
    qs = qs.filter(models_q_org(org_id))
    policies = [p for p in qs if p.applies_to_resource(resource_type)]
    if not policies:
        return result

    server_url = getattr(settings, 'OPA_SERVER_URL', '')
    timeout_ms = int(getattr(settings, 'OPA_EVALUATION_TIMEOUT_MS', 2000))
    fail_mode = getattr(settings, 'OPA_FAIL_MODE', 'allow')

    user = getattr(request, 'user', None)
    template = getattr(unified_job, 'unified_job_template', None) or getattr(unified_job, 'job_template', None)

    from forge.main.observability.tracing import span as _otel_span
    from forge.main.observability import metrics as _otel_metrics

    for policy in policies:
        eff = effective_enforcement(True, org_enforcement, policy.enforcement)
        if eff == ENFORCEMENT_NONE:
            continue

        try:
            with _otel_span(
                'forge.policy.evaluate',
                policy_id=getattr(policy, 'id', None),
                policy_name=getattr(policy, 'name', ''),
            ):
                opa_result = opa_evaluate(server_url, policy.package_path, context, timeout_ms)
            warns, denies = parse_decision(opa_result)
            _otel_metrics.inc_policy_evaluations('deny' if denies else ('warn' if warns else 'allow'))
        except OPAUnavailable as e:
            decision_kind = fail_mode_decision(True, fail_mode)
            msg = f'OPA unavailable: {e}'
            pd = PolicyDecision.objects.create(
                policy=policy, policy_name=policy.name,
                decision='deny' if decision_kind == 'deny' else 'warn',
                unified_job=unified_job if decision_kind != 'deny' else None,
                unified_job_template=template,
                organization_id=org_id,
                triggered_by=user if user and user.is_authenticated else None,
                message=msg,
                context=context,
            )
            result.decisions.append(pd)
            if decision_kind == 'deny':
                result.allowed = False
                result.deny_messages.append(msg)
            else:
                result.warn_messages.append(msg)
            continue

        if not warns and not denies:
            continue  # silent allow

        Policy.objects.filter(pk=policy.pk).update(
            trigger_count=policy.trigger_count + 1,
            last_triggered_at=now(),
            last_evaluated_at=now(),
        )

        for w in warns:
            pd = PolicyDecision.objects.create(
                policy=policy, policy_name=policy.name,
                decision=DECISION_WARN,
                unified_job=unified_job,
                unified_job_template=template,
                organization_id=org_id,
                triggered_by=user if user and user.is_authenticated else None,
                message=w,
                context=context,
            )
            result.decisions.append(pd)
            result.warn_messages.append(f'[{policy.name}] {w}')

        for d in denies:
            pd = PolicyDecision.objects.create(
                policy=policy, policy_name=policy.name,
                decision=DECISION_DENY,
                unified_job=unified_job if eff == ENFORCEMENT_WARN else None,
                unified_job_template=template,
                organization_id=org_id,
                triggered_by=user if user and user.is_authenticated else None,
                message=d,
                context=context,
            )
            result.decisions.append(pd)
            if eff == ENFORCEMENT_ENFORCE:
                result.allowed = False
                result.deny_messages.append(f'[{policy.name}] {d}')
            else:
                result.warn_messages.append(f'[{policy.name}] (deny in warn-only) {d}')

    return result


def models_q_org(org_id):
    """Helper: 'org match OR global'."""
    from django.db.models import Q
    if org_id is None:
        return Q(organization__isnull=True)
    return Q(organization_id=org_id) | Q(organization__isnull=True)
