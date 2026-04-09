"""Observability (OpenTelemetry) REST view.

Exposes the current OTel config and a best-effort collector health probe.
Read-only; configuration lives in env vars / Settings → System.
"""

import logging

from django.conf import settings
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response

from forge.api.generics import APIView
from forge.api.serializers.observability import ObservabilityConfigSerializer

logger = logging.getLogger('forge.api.views.observability')


class ObservabilityConfig(APIView):
    """GET /api/v2/observability/ — current OTel state + collector health."""

    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request, *args, **kwargs):
        enabled = bool(getattr(settings, 'OTEL_ENABLED', False))
        service_name = str(getattr(settings, 'OTEL_SERVICE_NAME', 'forge') or 'forge')
        endpoint = str(
            getattr(settings, 'OTEL_EXPORTER_ENDPOINT',
                    'http://forge-otel-collector:4317') or ''
        )
        sampler = str(
            getattr(settings, 'OTEL_TRACES_SAMPLER', 'parentbased_traceidratio')
            or 'parentbased_traceidratio'
        )
        sampler_arg = str(getattr(settings, 'OTEL_TRACES_SAMPLER_ARG', '0.1') or '0.1')

        healthy = False
        last_check = None
        if enabled and endpoint:
            try:
                from forge.main.observability.health import (
                    check_collector_health,
                    last_check_iso,
                )
                healthy = check_collector_health(endpoint)
                last_check = last_check_iso(endpoint)
            except Exception as e:  # pylint: disable=broad-except
                logger.debug('collector health check failed: %s', e)

        payload = {
            'enabled': enabled,
            'service_name': service_name,
            'exporter_endpoint': endpoint,
            'sampler': sampler,
            'sampler_arg': sampler_arg,
            'collector_healthy': healthy,
            'collector_last_check': last_check,
        }
        return Response(ObservabilityConfigSerializer(payload).data)
