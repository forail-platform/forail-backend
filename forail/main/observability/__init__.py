"""OpenTelemetry observability integration for Forail Platform.

Public surface:
  - init_observability(): idempotent boot hook called from wsgi/asgi/worker.
  - tracer / metrics_emitter: lazy accessors (no-op when SDK not initialized).
  - Pure helpers re-exported for unit testing and internal consumers.

Design contract: when OTEL_ENABLED is False (default), importing this package
and calling init_observability() MUST NOT import any opentelemetry module.
"""

from forail.main.observability.helpers import (
    parse_resource_attributes,
    parse_endpoint,
    is_otlp_grpc,
    is_otlp_http,
    validate_sampler_arg,
    aggregate_health,
    should_recheck_health,
)
from forail.main.observability.bootstrap import init_observability
from forail.main.observability import metrics as metrics_emitter  # noqa: F401
from forail.main.observability.tracing import span, tracer  # noqa: F401

__all__ = [
    'init_observability',
    'tracer',
    'metrics_emitter',
    'span',
    'parse_resource_attributes',
    'parse_endpoint',
    'is_otlp_grpc',
    'is_otlp_http',
    'validate_sampler_arg',
    'aggregate_health',
    'should_recheck_health',
]
