"""Pure recommendation rules.

Each rule is a tiny function that receives a ``RuleContext`` and returns
either a ``Recommendation`` or ``None``. No Django imports allowed here so
the module can be exercised by standalone unit tests.
"""

from datetime import datetime, timedelta, timezone

from .types import (
    Recommendation,
    RuleContext,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SEVERITY_CRITICAL,
)


def rule_no_scanners(ctx: RuleContext):
    if ctx.job_templates_total > 0 and ctx.scanners_enabled_count == 0:
        return Recommendation(
            id='no_scanners',
            scope='compliance',
            severity=SEVERITY_WARN,
            title='No IaC scanners configured',
            why='You have job templates but no IaC scanners. Enable scanning to catch unsafe playbooks before they run.',
            action_link='/wizards/compliance',
        )
    return None


def rule_all_policies_warn(ctx: RuleContext):
    if ctx.policies_total > 0 and ctx.policies_enforce_count == 0:
        return Recommendation(
            id='all_policies_warn',
            scope='compliance',
            severity=SEVERITY_INFO,
            title='All policies are in warn mode',
            why='None of your policies are currently enforcing. Promote tested policies to enforce to actually block violations.',
            action_link='/policies',
        )
    return None


def rule_multi_org_no_tenancy(ctx: RuleContext):
    if ctx.organizations_total > 1 and not ctx.tenancy_enabled:
        return Recommendation(
            id='multi_org_no_tenancy',
            scope='tenancy',
            severity=SEVERITY_WARN,
            title='Multiple organizations without tenancy',
            why='You have more than one organization but tenancy is disabled. Enable tenancy to enforce quotas and isolation.',
            action_link='/wizards/tenancy',
        )
    return None


def rule_no_observability(ctx: RuleContext):
    if not ctx.otel_enabled:
        return Recommendation(
            id='no_observability',
            scope='dashboard',
            severity=SEVERITY_INFO,
            title='Observability is not enabled',
            why='OpenTelemetry exporters are off. Enable them to get traces, metrics, and logs flowing to your backend.',
            action_link='/wizards/observability',
        )
    return None


def rule_stale_project(ctx: RuleContext):
    if not ctx.projects:
        return None
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=14)
    for name, last_sync in ctx.projects:
        stale = False
        if last_sync is None:
            stale = True
        else:
            try:
                ts = datetime.fromisoformat(last_sync)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < threshold:
                    stale = True
            except (ValueError, TypeError):
                stale = True
        if stale:
            return Recommendation(
                id='stale_project',
                scope='automation',
                severity=SEVERITY_INFO,
                title='Stale project detected',
                why=f'Project "{name}" has not been synced in over 14 days. Re-sync to pick up upstream changes.',
                action_link='/projects',
            )
    return None


def rule_no_schedules(ctx: RuleContext):
    if ctx.job_templates_total > 0 and ctx.schedules_total == 0:
        return Recommendation(
            id='no_schedules',
            scope='automation',
            severity=SEVERITY_INFO,
            title='No schedules defined',
            why='You have job templates but no schedules. Add schedules to run them automatically.',
            action_link='/schedules',
        )
    return None


def rule_no_drift(ctx: RuleContext):
    if ctx.job_templates_total > 0 and ctx.drift_detections_total == 0:
        return Recommendation(
            id='no_drift',
            scope='compliance',
            severity=SEVERITY_INFO,
            title='Drift detection not running',
            why='No drift detections recorded. Configure drift checks so configuration changes outside Forge are caught early.',
            action_link='/wizards/compliance',
        )
    return None


def rule_few_surveys(ctx: RuleContext):
    if ctx.job_templates_total < 2:
        return None
    if ctx.job_templates_total > 0 and ctx.surveys_total < ctx.job_templates_total * 0.5:
        return Recommendation(
            id='few_surveys',
            scope='self_service',
            severity=SEVERITY_INFO,
            title='Few job templates expose surveys',
            why='Less than half of your job templates expose a survey. Surveys make templates self-service friendly.',
            action_link='/job_templates',
        )
    return None


def rule_tenant_near_quota(ctx: RuleContext):
    for name, pct in ctx.tenant_usage:
        try:
            if pct > 80:
                return Recommendation(
                    id='tenant_near_quota',
                    scope='tenancy',
                    severity=SEVERITY_WARN,
                    title='Tenant near concurrent-job quota',
                    why=f'Tenant "{name}" is using {pct:.0f}% of its concurrent job limit. Consider raising the quota.',
                    action_link='/tenants',
                )
        except (TypeError, ValueError):
            continue
    return None


def rule_no_catalog_items(ctx: RuleContext):
    if ctx.job_templates_total > 0 and ctx.catalog_items_total == 0:
        return Recommendation(
            id='no_catalog_items',
            scope='self_service',
            severity=SEVERITY_INFO,
            title='Service catalog is empty',
            why='You have job templates but no catalog items. Publish some to give end users a self-service entry point.',
            action_link='/wizards/self-service',
        )
    return None


def rule_only_default_team(ctx: RuleContext):
    if ctx.teams_count <= 1:
        return Recommendation(
            id='only_default_team',
            scope='access',
            severity=SEVERITY_INFO,
            title='Only the default team exists',
            why='Create additional teams to delegate access and separate duties across your organization.',
            action_link='/teams',
        )
    return None


def rule_default_admin_password(ctx: RuleContext):
    if ctx.admin_default_password is True:
        return Recommendation(
            id='default_admin_password',
            scope='dashboard',
            severity=SEVERITY_CRITICAL,
            title='Default admin password in use',
            why='The admin user is still using the default password. Change it immediately to secure your installation.',
            action_link='/users',
        )
    return None


ALL_RULES = [
    ('compliance', rule_no_scanners),
    ('compliance', rule_all_policies_warn),
    ('tenancy', rule_multi_org_no_tenancy),
    ('dashboard', rule_no_observability),
    ('automation', rule_stale_project),
    ('automation', rule_no_schedules),
    ('compliance', rule_no_drift),
    ('self_service', rule_few_surveys),
    ('tenancy', rule_tenant_near_quota),
    ('self_service', rule_no_catalog_items),
    ('access', rule_only_default_team),
    ('dashboard', rule_default_admin_password),
]
