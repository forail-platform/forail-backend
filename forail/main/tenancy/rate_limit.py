"""Per-tenant API rate limiting middleware — Multi-Tenancy v2.

Uses a Redis-backed token bucket to enforce per-tenant request rate limits.
Each tenant Organization gets its own bucket keyed by ``tenant_ratelimit:{org_id}``.

When the bucket is empty the middleware returns HTTP 429 with a ``Retry-After``
header.  Requests from superusers, unauthenticated users, non-tenant users,
or when the feature is disabled pass through unconditionally.
"""

import logging
import time

from django.conf import settings
from django.http import JsonResponse

from forail.main.tenancy.helpers import (
    TOKEN_BUCKET_LUA,
    compute_token_bucket_params,
)

logger = logging.getLogger('forail.main.tenancy.rate_limit')

_lua_sha = None


def _get_redis():
    """Return the default Redis connection used by AWX/Forail."""
    from django.core.cache import caches
    try:
        cache = caches['default']
        # django-redis exposes .client.get_client()
        client = cache.client.get_client()
        return client
    except Exception:
        logger.debug('rate_limit: could not get Redis client', exc_info=True)
        return None


def _ensure_script(redis_client):
    """Register the Lua script and cache the SHA."""
    global _lua_sha
    if _lua_sha is None:
        _lua_sha = redis_client.script_load(TOKEN_BUCKET_LUA)
    return _lua_sha


class TenantRateLimitMiddleware:
    """Token-bucket rate limiter per tenant, backed by Redis."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Guard: feature switch
        if not getattr(settings, 'TENANCY_ENABLED', False):
            return self.get_response(request)
        if not getattr(settings, 'TENANCY_RATE_LIMITING_ENABLED', False):
            return self.get_response(request)

        user = getattr(request, 'user', None)
        if user is None or not getattr(user, 'is_authenticated', False):
            return self.get_response(request)
        if getattr(user, 'is_superuser', False):
            return self.get_response(request)

        # Use the tenant org stashed by TenantIsolationMiddleware.
        tenant_org = getattr(request, '_tenant_org', None)
        if tenant_org is None:
            return self.get_response(request)

        # Determine rate limit: per-tenant override, then global default.
        rate_limit = getattr(tenant_org, 'tenant_api_rate_limit', None) or 0
        if not rate_limit:
            rate_limit = getattr(settings, 'TENANCY_DEFAULT_API_RATE_LIMIT', 0)
        if not rate_limit:
            return self.get_response(request)

        max_tokens, refill_rate = compute_token_bucket_params(rate_limit)
        if max_tokens <= 0:
            return self.get_response(request)

        # L7: the limiter's behaviour when Redis is unavailable is a conscious
        # trade-off. It fails OPEN by default (an outage must not take the whole
        # API down), but operators who prefer availability-of-isolation over
        # availability-of-service can set TENANCY_RATE_LIMIT_FAIL_CLOSED=True to
        # return 503 instead. Either way the outage is logged loudly, not
        # swallowed at debug level.
        fail_closed = getattr(settings, 'TENANCY_RATE_LIMIT_FAIL_CLOSED', False)

        def _on_redis_unavailable(reason):
            if fail_closed:
                logger.warning('rate_limit: Redis unavailable (%s) — failing CLOSED (503) org=%s',
                               reason, tenant_org.pk)
                return JsonResponse(
                    {'detail': 'Rate limiter temporarily unavailable.'}, status=503,
                )
            logger.warning('rate_limit: Redis unavailable (%s) — failing open, throttle bypassed org=%s',
                           reason, tenant_org.pk)
            return self.get_response(request)

        # Check the bucket.
        try:
            redis_client = _get_redis()
            if redis_client is None:
                return _on_redis_unavailable('no client')

            sha = _ensure_script(redis_client)
            key = f'tenant_ratelimit:{tenant_org.pk}'
            now = time.time()

            result = redis_client.evalsha(
                sha, 1, key,
                str(max_tokens), str(refill_rate), str(now), '1',
            )
            allowed = int(result[0])
            # tokens_remaining = int(result[1])

            if not allowed:
                retry_after = max(1, round(1.0 / refill_rate))
                logger.info(
                    'tenant_rate_limit: THROTTLED org=%s rate=%d/s',
                    tenant_org.pk, rate_limit,
                )
                response = JsonResponse(
                    {
                        'detail': 'Tenant API rate limit exceeded.',
                        'retry_after': retry_after,
                    },
                    status=429,
                )
                response['Retry-After'] = str(retry_after)
                return response

        except Exception:
            logger.warning('rate_limit: Redis error', exc_info=True)
            return _on_redis_unavailable('redis error')

        return self.get_response(request)
