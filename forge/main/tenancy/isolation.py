"""Cross-tenant isolation middleware.

v1: audit hook stub. The middleware is installed but only logs an INFO
line when the request user belongs to an Organization with
``tenant_isolation_strict=True``. Full queryset instrumentation and
``TenantIsolationEvent`` emission is deferred to v2.
"""

import logging

logger = logging.getLogger('forge.main.tenancy.isolation')


class TenantIsolationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            user = getattr(request, 'user', None)
            if user is None or not getattr(user, 'is_authenticated', False):
                return response
            # Best-effort primary org discovery.
            try:
                orgs = list(user.organizations.all()[:1])
            except Exception:  # pylint: disable=broad-except
                orgs = []
            if not orgs:
                return response
            primary_org = orgs[0]
            if getattr(primary_org, 'tenant_isolation_strict', False):
                # v1: audit hook stub — log only, do not emit events or block.
                logger.info(
                    'tenant_isolation_strict enabled for user=%s org=%s path=%s',
                    getattr(user, 'pk', None),
                    getattr(primary_org, 'pk', None),
                    getattr(request, 'path', ''),
                )
        except Exception:  # pylint: disable=broad-except
            logger.debug('TenantIsolationMiddleware no-op failed', exc_info=True)
        return response
