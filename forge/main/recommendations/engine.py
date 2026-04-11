"""Recommendations engine.

``evaluate`` is pure (no Django). ``build_context`` is the only function
that touches the database; it lazy-imports Django models and wraps every
query in try/except so a missing model never breaks the whole engine.
"""

import time

from .types import Recommendation, RuleContext, _SEVERITY_ORDER
from .rules import ALL_RULES


_CACHE = {'ts': 0.0, 'ctx': None}
_CACHE_TTL_SECONDS = 60


def evaluate(scope: str, ctx: RuleContext):
    """Run rules matching ``scope`` (or all when scope == 'all') against ``ctx``."""
    results = []
    for rule_scope, fn in ALL_RULES:
        if scope != 'all' and rule_scope != scope:
            continue
        try:
            rec = fn(ctx)
        except Exception:
            rec = None
        if rec is not None:
            results.append(rec)
    results.sort(key=lambda r: _SEVERITY_ORDER.get(r.severity, 99))
    return results


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def build_context() -> RuleContext:
    """Inspect current DB state and build a RuleContext. Cached for 60s."""
    now = time.time()
    if _CACHE['ctx'] is not None and (now - _CACHE['ts']) < _CACHE_TTL_SECONDS:
        return _CACHE['ctx']

    ctx = RuleContext()

    # Scanners
    def _scanners():
        from forge.main.models import Scanner
        return Scanner.objects.filter(enabled=True).count()
    ctx.scanners_enabled_count = _safe(_scanners, 0)

    # Policies
    def _policies_total():
        from forge.main.models import Policy
        return Policy.objects.count()
    ctx.policies_total = _safe(_policies_total, 0)

    def _policies_enforce():
        from forge.main.models import Policy
        return Policy.objects.filter(mode='enforce').count()
    ctx.policies_enforce_count = _safe(_policies_enforce, 0)

    # Organizations
    def _orgs():
        from forge.main.models import Organization
        return Organization.objects.count()
    ctx.organizations_total = _safe(_orgs, 0)

    # Settings flags
    def _tenancy():
        from django.conf import settings
        return bool(getattr(settings, 'TENANCY_ENABLED', False))
    ctx.tenancy_enabled = _safe(_tenancy, False)

    def _otel():
        from django.conf import settings
        return bool(getattr(settings, 'OTEL_ENABLED', False) or getattr(settings, 'OBSERVABILITY_ENABLED', False))
    ctx.otel_enabled = _safe(_otel, False)

    # Job templates
    def _jts():
        from forge.main.models import JobTemplate
        return JobTemplate.objects.count()
    ctx.job_templates_total = _safe(_jts, 0)

    # Schedules
    def _schedules():
        from forge.main.models import Schedule
        return Schedule.objects.count()
    ctx.schedules_total = _safe(_schedules, 0)

    # Catalog items
    def _catalog():
        from forge.main import models as m
        for name in ('ServiceCatalogItem', 'CatalogItem'):
            mdl = getattr(m, name, None)
            if mdl is not None:
                return mdl.objects.count()
        return 0
    ctx.catalog_items_total = _safe(_catalog, 0)

    # Surveys
    def _surveys():
        from forge.main.models import JobTemplate
        return JobTemplate.objects.exclude(survey_spec={}).exclude(survey_spec__isnull=True).count()
    ctx.surveys_total = _safe(_surveys, 0)

    # Drift detections
    def _drift():
        from forge.main import models as m
        for name in ('DriftDetection', 'Drift'):
            mdl = getattr(m, name, None)
            if mdl is not None:
                return mdl.objects.count()
        return 0
    ctx.drift_detections_total = _safe(_drift, 0)

    # Projects
    def _projects():
        from forge.main.models import Project
        out = []
        for p in Project.objects.all()[:50]:
            last = None
            lj = getattr(p, 'last_job_run', None)
            if lj:
                try:
                    last = lj.isoformat()
                except Exception:
                    last = None
            out.append((getattr(p, 'name', 'unknown'), last))
        return out
    ctx.projects = _safe(_projects, [])

    # Tenant usage
    def _tenant_usage():
        from forge.main.models import Organization
        out = []
        qs = Organization.objects.filter(is_tenant_root=True)
        for org in qs:
            limit = getattr(org, 'tenant_max_concurrent_jobs', 0) or 0
            if limit <= 0:
                continue
            current = getattr(org, 'tenant_current_concurrent_jobs', 0) or 0
            pct = (current / limit) * 100.0
            out.append((getattr(org, 'name', 'unknown'), pct))
        return out
    ctx.tenant_usage = _safe(_tenant_usage, [])

    # Teams
    def _teams():
        from forge.main.models import Team
        return Team.objects.count()
    ctx.teams_count = _safe(_teams, 0)

    # Admin default password
    def _admin_default():
        from forge.main.models import User
        user = User.objects.filter(username='admin').first()
        if user is None:
            return False
        return bool(user.check_password('admin'))
    ctx.admin_default_password = _safe(_admin_default, False)

    _CACHE['ctx'] = ctx
    _CACHE['ts'] = now
    return ctx
