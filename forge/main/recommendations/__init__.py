"""Recommendations engine: rule-based inspection of current state."""

from .types import (
    Recommendation,
    RuleContext,
    SEVERITY_INFO,
    SEVERITY_WARN,
    SEVERITY_CRITICAL,
)

__all__ = [
    'Recommendation',
    'RuleContext',
    'SEVERITY_INFO',
    'SEVERITY_WARN',
    'SEVERITY_CRITICAL',
]
