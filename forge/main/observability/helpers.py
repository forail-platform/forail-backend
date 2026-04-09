"""Pure helper functions for the observability subsystem.

These helpers have NO Django and NO opentelemetry dependency so they can be
exercised directly from standalone unit tests via importlib.
"""

from datetime import datetime, timezone


def parse_resource_attributes(s):
    """Parse an OTEL_RESOURCE_ATTRIBUTES-style string.

    Accepts comma-separated ``key=value`` pairs. Whitespace is stripped around
    both keys and values. Malformed pairs (no ``=``) are skipped silently. An
    empty string yields an empty dict.
    """
    out = {}
    if not s:
        return out
    for pair in s.split(','):
        if '=' not in pair:
            continue
        k, _, v = pair.partition('=')
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        out[k] = v
    return out


def parse_endpoint(url):
    """Parse an OTLP endpoint URL into ``(host, port, scheme)``.

    Supports ``http://host:port``, ``https://host:port`` and bare ``host:port``.
    When the scheme is omitted, it defaults to ``http``. When the port is
    omitted, it defaults to ``4317`` (OTLP/gRPC).
    """
    if not url:
        return ('', 4317, 'http')
    scheme = 'http'
    rest = url
    if '://' in rest:
        scheme, _, rest = rest.partition('://')
    # Strip any path component
    if '/' in rest:
        rest, _, _ = rest.partition('/')
    host = rest
    port = 4317
    if ':' in rest:
        host, _, port_s = rest.rpartition(':')
        try:
            port = int(port_s)
        except ValueError:
            port = 4317
    return (host, port, scheme)


def is_otlp_grpc(endpoint):
    """Return True when the endpoint looks like OTLP/gRPC (port 4317)."""
    _, port, _ = parse_endpoint(endpoint)
    return port == 4317


def is_otlp_http(endpoint):
    """Return True when the endpoint looks like OTLP/HTTP (port 4318 or /v1/)."""
    if endpoint and '/v1/' in endpoint:
        return True
    _, port, _ = parse_endpoint(endpoint)
    return port == 4318


def validate_sampler_arg(arg):
    """Parse a sampler arg string into a float clamped to [0, 1].

    Invalid input falls back to the OTel default of 0.1.
    """
    try:
        v = float(arg)
    except (TypeError, ValueError):
        return 0.1
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _parse_iso(s):
    if not s:
        return None
    try:
        # Accept trailing Z
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def aggregate_health(last_check_iso, ttl_seconds=30, now=None):
    """Return True when the last collector check is within ttl_seconds of now."""
    if last_check_iso is None:
        return False
    dt = _parse_iso(last_check_iso) if isinstance(last_check_iso, str) else last_check_iso
    if dt is None:
        return False
    current = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    delta = (current - dt).total_seconds()
    return 0 <= delta <= ttl_seconds


def should_recheck_health(last_check_iso, ttl_seconds=30, now=None):
    """Opposite of :func:`aggregate_health` — True when cache is stale/missing."""
    return not aggregate_health(last_check_iso, ttl_seconds=ttl_seconds, now=now)
