"""Multi-Tenancy v1 serializers."""

from rest_framework import serializers

from forge.main.models import Organization
from forge.main.models.tenancy import (
    TenantUsage,
    TenantQuotaEvent,
    TenantIsolationEvent,
)
from forge.main.tenancy.helpers import validate_provisioning_payload


class TenantQuotaSerializer(serializers.Serializer):
    max_concurrent_jobs = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    max_daily_launches = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    max_hosts = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    max_storage_mb = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    api_rate_limit = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class TenantBrandingSerializer(serializers.Serializer):
    logo_url = serializers.CharField(required=False, allow_blank=True, max_length=512)
    primary_color = serializers.CharField(required=False, allow_blank=True, max_length=16)
    secondary_color = serializers.CharField(required=False, allow_blank=True, max_length=16)
    custom_domain = serializers.CharField(required=False, allow_blank=True, max_length=255)


class TenantUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantUsage
        fields = [
            'concurrent_jobs_count',
            'launches_today_count',
            'launches_today_window_start',
            'hosts_count',
            'storage_mb_used',
            'last_recalculated_at',
        ]
        read_only_fields = fields


class TenantSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()
    contact_email = serializers.CharField(source='tenant_contact_email', required=False, allow_blank=True)
    isolation_strict = serializers.BooleanField(source='tenant_isolation_strict', required=False)
    quota = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()
    branding = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            'id', 'type', 'url', 'related',
            'name', 'description',
            'is_tenant_root',
            'contact_email', 'isolation_strict',
            'quota', 'usage', 'branding',
            'created', 'modified',
        ]
        read_only_fields = ['id', 'created', 'modified', 'usage']

    def get_type(self, obj):
        return 'tenant'

    def get_url(self, obj):
        return f'/api/v2/tenants/{obj.pk}/'

    def get_related(self, obj):
        return {
            'organization': f'/api/v2/organizations/{obj.pk}/',
            'recalculate': f'/api/v2/tenants/{obj.pk}/recalculate/',
            'quota_events': f'/api/v2/tenant_quota_events/?organization={obj.pk}',
        }

    def get_quota(self, obj):
        return {
            'max_concurrent_jobs': obj.tenant_max_concurrent_jobs,
            'max_daily_launches': obj.tenant_max_daily_launches,
            'max_hosts': obj.tenant_max_hosts,
            'max_storage_mb': obj.tenant_max_storage_mb,
            'api_rate_limit': obj.tenant_api_rate_limit,
        }

    def get_usage(self, obj):
        usage = getattr(obj, 'tenant_usage', None)
        if usage is None:
            return {
                'concurrent_jobs_count': 0,
                'launches_today_count': 0,
                'launches_today_window_start': None,
                'hosts_count': 0,
                'storage_mb_used': 0,
                'last_recalculated_at': None,
            }
        return TenantUsageSerializer(usage).data

    def get_branding(self, obj):
        return {
            'logo_url': obj.tenant_logo_url or '',
            'primary_color': obj.tenant_primary_color or '',
            'secondary_color': obj.tenant_secondary_color or '',
            'custom_domain': obj.tenant_custom_domain or '',
        }

    def update(self, instance, validated_data):
        # Support PATCH updates for nested quota/branding via request.data
        request = self.context.get('request')
        data = getattr(request, 'data', {}) if request is not None else {}

        if 'tenant_contact_email' in validated_data:
            instance.tenant_contact_email = validated_data['tenant_contact_email']
        if 'tenant_isolation_strict' in validated_data:
            instance.tenant_isolation_strict = validated_data['tenant_isolation_strict']
        if 'name' in validated_data:
            instance.name = validated_data['name']
        if 'description' in validated_data:
            instance.description = validated_data['description']

        quota = data.get('quota') if isinstance(data, dict) else None
        if isinstance(quota, dict):
            if 'max_concurrent_jobs' in quota:
                instance.tenant_max_concurrent_jobs = quota['max_concurrent_jobs'] or None
            if 'max_daily_launches' in quota:
                instance.tenant_max_daily_launches = quota['max_daily_launches'] or None
            if 'max_hosts' in quota:
                instance.tenant_max_hosts = quota['max_hosts'] or None
            if 'max_storage_mb' in quota:
                instance.tenant_max_storage_mb = quota['max_storage_mb'] or None
            if 'api_rate_limit' in quota:
                instance.tenant_api_rate_limit = quota['api_rate_limit'] or None

        branding = data.get('branding') if isinstance(data, dict) else None
        if isinstance(branding, dict):
            if 'logo_url' in branding:
                instance.tenant_logo_url = branding['logo_url'] or ''
            if 'primary_color' in branding:
                instance.tenant_primary_color = branding['primary_color'] or ''
            if 'secondary_color' in branding:
                instance.tenant_secondary_color = branding['secondary_color'] or ''
            if 'custom_domain' in branding:
                instance.tenant_custom_domain = branding['custom_domain'] or ''

        instance.save()
        return instance


class TenantProvisionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=512)
    description = serializers.CharField(required=False, allow_blank=True)
    admin_username = serializers.CharField()
    admin_email = serializers.CharField()
    admin_password = serializers.CharField(write_only=True)
    contact_email = serializers.CharField(required=False, allow_blank=True)
    isolation_strict = serializers.BooleanField(required=False, default=False)
    quota = TenantQuotaSerializer(required=False)
    branding = TenantBrandingSerializer(required=False)

    def validate(self, attrs):
        errors = validate_provisioning_payload(self.initial_data)
        if errors:
            raise serializers.ValidationError({'errors': errors})
        return attrs


class TenantQuotaEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantQuotaEvent
        fields = [
            'id', 'organization', 'organization_name',
            'quota_kind', 'decision',
            'current_value', 'limit_value',
            'triggered_by', 'unified_job_template',
            'message', 'created',
        ]
        read_only_fields = fields


class TenantIsolationEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantIsolationEvent
        fields = [
            'id', 'user', 'user_organization', 'accessed_organization',
            'resource_type', 'resource_id', 'request_path',
            'blocked', 'created',
        ]
        read_only_fields = fields


class BrandingPublicSerializer(serializers.Serializer):
    tenant_id = serializers.IntegerField()
    name = serializers.CharField()
    logo_url = serializers.CharField(allow_blank=True)
    primary_color = serializers.CharField(allow_blank=True)
    secondary_color = serializers.CharField(allow_blank=True)
    contact_email = serializers.CharField(allow_blank=True)
