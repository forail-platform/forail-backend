"""Pure dataclasses for the recommendations engine.

This module MUST NOT import Django or any other heavy dependency so that
it remains importable from standalone unit tests.
"""

from dataclasses import dataclass, field, asdict


SEVERITY_INFO = 'info'
SEVERITY_WARN = 'warn'
SEVERITY_CRITICAL = 'critical'

_SEVERITY_ORDER = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_WARN: 1,
    SEVERITY_INFO: 2,
}


@dataclass
class Recommendation:
    id: str
    scope: str
    severity: str
    title: str
    why: str
    action_link: str

    def to_dict(self):
        return asdict(self)


@dataclass
class RuleContext:
    scanners_enabled_count: int = 0
    policies_total: int = 0
    policies_enforce_count: int = 0
    organizations_total: int = 0
    tenancy_enabled: bool = False
    otel_enabled: bool = False
    job_templates_total: int = 0
    schedules_total: int = 0
    catalog_items_total: int = 0
    surveys_total: int = 0
    drift_detections_total: int = 0
    projects: list = field(default_factory=list)
    tenant_usage: list = field(default_factory=list)
    teams_count: int = 0
    admin_default_password: bool = False
