"""Bootstrap the OpenTelemetry SDK for Forail.

CRITICAL: when OTEL_ENABLED is False or unset, ``init_observability`` must
return without importing any ``opentelemetry`` module. This is enforced by
doing all SDK imports lazily inside the guarded branch.
"""

import logging
import os

logger = logging.getLogger('forail.main.observability.bootstrap')

_INITIALIZED = False

# Env vars that should be one-way synced into the DB-backed Setting registry
# at boot. Allows operators to flip OTEL_ENABLED via docker-compose env without
# also having to click through the Settings UI. Env wins on first boot;
# operators can still override via the UI later.
_ENV_SYNC_KEYS = (
    'OTEL_ENABLED',
    'OTEL_EXPORTER_ENDPOINT',
    'OTEL_SERVICE_NAME',
    'OTEL_TRACES_SAMPLER',
    'OTEL_TRACES_SAMPLER_ARG',
    'TENANCY_ENABLED',
)

_BOOL_KEYS = ('OTEL_ENABLED', 'TENANCY_ENABLED')


def _coerce_env_value(key, raw):
    """Convert a raw env string into the right Python type for the Setting row.

    Bool keys get parsed via :func:`parse_env_bool`; everything else stays a
    string. The ``Setting.value`` field is a JSONField so the type matters at
    the storage layer.
    """
    if key in _BOOL_KEYS:
        from forail.main.observability.helpers import parse_env_bool
        return parse_env_bool(raw)
    return str(raw)


def sync_env_to_settings():
    """Mirror OTEL_* env vars into the DB Setting registry.

    One-way: env value wins on each call IF different from the current setting.
    Operator UI overrides persist as long as the env var is unset. Wrapped in
    broad try/except so DB-not-ready never crashes startup.
    """
    try:
        from forail.conf.models import Setting
    except Exception:
        return
    for key in _ENV_SYNC_KEYS:
        raw = os.environ.get(key)
        if raw is None:
            continue
        try:
            value = _coerce_env_value(key, raw)
            Setting.objects.update_or_create(
                key=key,
                user=None,
                defaults={'value': value},
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.warning('OTel env sync skipped key %s: %s', key, e)


def _env_or_setting(name, default=None):
    if name in os.environ:
        return os.environ[name]
    try:
        from django.conf import settings
        val = getattr(settings, name, None)
        if val is not None:
            return val
    except Exception:
        pass
    return default


def _env_or_setting_bool(name, default=False):
    val = _env_or_setting(name, default)
    if isinstance(val, bool):
        return val
    if val is None:
        return default
    return str(val).strip().lower() in ('1', 'true', 'yes', 'on')


def init_observability():
    """Idempotent OpenTelemetry SDK boot.

    Reads env vars (then Django settings) to discover the OTel configuration.
    Registers Django/Celery/Requests/Psycopg2 auto-instrumentations. All
    failures are swallowed with a warning so a misconfigured collector can
    never prevent Django startup.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    sync_env_to_settings()

    if not _env_or_setting_bool('OTEL_ENABLED', default=False):
        return

    try:
        # Lazy SDK imports -- never touched when OTEL_ENABLED is False.
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import (
            ALWAYS_ON,
            ALWAYS_OFF,
            ParentBased,
            TraceIdRatioBased,
        )
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter,
        )

        from forail.main.observability.helpers import (
            parse_resource_attributes,
            validate_sampler_arg,
        )

        service_name = str(
            _env_or_setting('OTEL_SERVICE_NAME', 'forail') or 'forail'
        )
        endpoint = str(
            _env_or_setting(
                'OTEL_EXPORTER_OTLP_ENDPOINT',
                _env_or_setting(
                    'OTEL_EXPORTER_ENDPOINT',
                    'http://forail-otel-collector:4317',
                ),
            )
            or 'http://forail-otel-collector:4317'
        )
        raw_attrs = str(_env_or_setting('OTEL_RESOURCE_ATTRIBUTES', '') or '')
        sampler_name = str(
            _env_or_setting('OTEL_TRACES_SAMPLER', 'parentbased_traceidratio')
            or 'parentbased_traceidratio'
        )
        sampler_arg = validate_sampler_arg(
            _env_or_setting('OTEL_TRACES_SAMPLER_ARG', '0.1')
        )

        attrs = parse_resource_attributes(raw_attrs)
        attrs.setdefault('service.name', service_name)
        resource = Resource.create(attrs)

        if sampler_name == 'always_on':
            sampler = ALWAYS_ON
        elif sampler_name == 'always_off':
            sampler = ALWAYS_OFF
        elif sampler_name == 'traceidratio':
            sampler = TraceIdRatioBased(sampler_arg)
        else:
            sampler = ParentBased(TraceIdRatioBased(sampler_arg))

        tracer_provider = TracerProvider(resource=resource, sampler=sampler)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
        )
        trace.set_tracer_provider(tracer_provider)

        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint, insecure=True)
        )
        meter_provider = MeterProvider(
            resource=resource, metric_readers=[metric_reader]
        )
        metrics.set_meter_provider(meter_provider)

        # Auto-instrumentation -- each wrapped individually so one missing
        # package does not break the others.
        for mod_path, cls_name in (
            ('opentelemetry.instrumentation.django', 'DjangoInstrumentor'),
            ('opentelemetry.instrumentation.celery', 'CeleryInstrumentor'),
            ('opentelemetry.instrumentation.requests', 'RequestsInstrumentor'),
            ('opentelemetry.instrumentation.psycopg2', 'Psycopg2Instrumentor'),
        ):
            try:
                mod = __import__(mod_path, fromlist=[cls_name])
                getattr(mod, cls_name)().instrument()
            except Exception as e:  # pylint: disable=broad-except
                logger.warning('OTel %s instrumentation skipped: %s', cls_name, e)

        # Mark metrics module as initialized so helpers stop being no-ops.
        from forail.main.observability import metrics as _metrics
        _metrics._initialized = True
        _metrics._meter = metrics.get_meter('forail')

        from forail.main.observability import tracing as _tracing
        _tracing._initialized = True
        _tracing._tracer = trace.get_tracer('forail')

        _INITIALIZED = True
        logger.info('OpenTelemetry initialized (endpoint=%s, sampler=%s)',
                    endpoint, sampler_name)
    except Exception as e:  # pylint: disable=broad-except
        logger.warning('OpenTelemetry initialization failed: %s', e)
