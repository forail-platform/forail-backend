"""Observability (OpenTelemetry) read-only serializers."""

from rest_framework import serializers


class ObservabilityConfigSerializer(serializers.Serializer):
    """Current OTel configuration plus best-effort collector health.

    All fields are read-only; configuration happens through env vars or
    the Settings registry, not through this endpoint.
    """

    enabled = serializers.BooleanField(read_only=True)
    service_name = serializers.CharField(read_only=True)
    exporter_endpoint = serializers.CharField(read_only=True, allow_blank=True)
    sampler = serializers.CharField(read_only=True)
    sampler_arg = serializers.CharField(read_only=True)
    collector_healthy = serializers.BooleanField(read_only=True)
    collector_last_check = serializers.CharField(read_only=True, allow_null=True)
