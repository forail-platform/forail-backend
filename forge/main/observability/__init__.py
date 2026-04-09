"""OpenTelemetry observability integration for Forge Platform.

Public surface:
  - init_observability(): idempotent boot hook called from wsgi/asgi/worker.
  - tracer / metrics_emitter: lazy accessors (no-op when SDK not initialized).
  - Pure helpers re-exported for unit testing and internal consumers.

Design contract: when OTEL_ENABLED is False (default), importing this package
and calling init_observability() MUST NOT import any opentelemetry module.
"""

from forge.main.observability.helpers import (
    parse_resource_attributes,
    parse_endpoint,
    is_otlp_grpc,
    is_otlp_http,
    validate_sampler_arg,
    aggregate_health,
    should_recheck_health,
)
from forge.main.observability.bootstrap import init_observability
from forge.main.observability import metrics as metrics_emitter  # noqa: F401
from forge.main.observability.tracing import span, tracer  # noqa: F401

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
