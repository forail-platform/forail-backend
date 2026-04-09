"""Best-effort OTel Collector health probe.

Performs a short TCP connect to the configured collector endpoint and
caches the result for 30 seconds in a module-level dict keyed by endpoint.
Never raises; on any failure returns False.
"""

import socket
import time

from forge.main.observability.helpers import parse_endpoint

_CACHE = {}  # endpoint -> (expires_at_monotonic, healthy, last_check_iso)


def check_collector_health(endpoint, timeout=0.5):
    if not endpoint:
        return False
    now = time.monotonic()
    cached = _CACHE.get(endpoint)
    if cached and cached[0] > now:
        return cached[1]
    host, port, _ = parse_endpoint(endpoint)
    healthy = False
    if host:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                healthy = True
        except (OSError, socket.timeout):
            healthy = False
    from datetime import datetime, timezone
    iso = datetime.now(timezone.utc).isoformat()
    _CACHE[endpoint] = (now + 30.0, healthy, iso)
    return healthy


def last_check_iso(endpoint):
    cached = _CACHE.get(endpoint)
    if not cached:
        return None
    return cached[2]
