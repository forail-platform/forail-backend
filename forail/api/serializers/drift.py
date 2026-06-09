"""Drift Detection serializers for the Forail API."""

from rest_framework import serializers

from forail.main.models.drift import (
    HostFactSnapshot,
    DriftDetection,
    DriftAlertRule,
    DriftAlert,
)


# ---------------------------------------------------------------------------
# HostFactSnapshot
# ---------------------------------------------------------------------------

class HostFactSnapshotSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = HostFactSnapshot
        fields = [
            'id', 'type', 'url', 'related',
            'host', 'job', 'inventory', 'organization',
            'captured_at', 'facts', 'facts_hash',
        ]
        read_only_fields = fields

    def get_type(self, obj):
        return 'fact_snapshot'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {}
        if obj.host_id:
            res['host'] = f'/api/v2/hosts/{obj.host_id}/'
        if obj.job_id:
            res['job'] = f'/api/v2/jobs/{obj.job_id}/'
        if obj.inventory_id:
            res['inventory'] = f'/api/v2/inventories/{obj.inventory_id}/'
        return res


class HostFactSnapshotListSerializer(HostFactSnapshotSerializer):
    """Lighter serializer for list views — excludes facts."""

    class Meta(HostFactSnapshotSerializer.Meta):
        fields = [
            'id', 'type', 'url',
            'host', 'job', 'inventory', 'organization',
            'captured_at', 'facts_hash',
        ]


# ---------------------------------------------------------------------------
# DriftDetection
# ---------------------------------------------------------------------------

class DriftDetectionSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()
    host_name = serializers.SerializerMethodField()

    class Meta:
        model = DriftDetection
        fields = [
            'id', 'type', 'url', 'related',
            'host', 'host_name', 'inventory', 'organization',
            'snapshot_before', 'snapshot_after',
            'detected_at', 'job',
            'category', 'severity', 'fact_path', 'summary', 'detail',
            'acknowledged', 'acknowledged_by', 'acknowledged_at',
        ]
        read_only_fields = fields

    def get_type(self, obj):
        return 'drift_detection'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {}
        if obj.host_id:
            res['host'] = f'/api/v2/hosts/{obj.host_id}/'
        if obj.job_id:
            res['job'] = f'/api/v2/jobs/{obj.job_id}/'
        if obj.snapshot_before_id:
            res['snapshot_before'] = f'/api/v2/fact_snapshots/{obj.snapshot_before_id}/'
        if obj.snapshot_after_id:
            res['snapshot_after'] = f'/api/v2/fact_snapshots/{obj.snapshot_after_id}/'
        return res

    def get_host_name(self, obj):
        if hasattr(obj, 'host') and obj.host:
            return obj.host.name
        return ''


class DriftDetectionListSerializer(DriftDetectionSerializer):
    """Lighter serializer for list views — excludes detail."""

    class Meta(DriftDetectionSerializer.Meta):
        fields = [
            'id', 'type', 'url',
            'host', 'host_name', 'inventory', 'organization',
            'detected_at', 'job',
            'category', 'severity', 'fact_path', 'summary',
            'acknowledged',
        ]


# ---------------------------------------------------------------------------
# DriftAlertRule
# ---------------------------------------------------------------------------

class DriftAlertRuleSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = DriftAlertRule
        fields = [
            'id', 'type', 'url', 'related',
            'created', 'modified',
            'name', 'description', 'organization', 'enabled',
            'inventory', 'host_filter', 'categories', 'severity_min',
            'threshold_count', 'threshold_window_minutes',
            'notification_template',
            'last_triggered_at', 'trigger_count', 'cooldown_minutes',
        ]
        read_only_fields = ['last_triggered_at', 'trigger_count', 'created', 'modified']

    def get_type(self, obj):
        return 'drift_alert_rule'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {}
        if obj.organization_id:
            res['organization'] = f'/api/v2/organizations/{obj.organization_id}/'
        if obj.inventory_id:
            res['inventory'] = f'/api/v2/inventories/{obj.inventory_id}/'
        if obj.notification_template_id:
            res['notification_template'] = f'/api/v2/notification_templates/{obj.notification_template_id}/'
        return res

    def validate_categories(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Categories must be a list.")
        valid = dict(DriftDetection.CATEGORY_CHOICES).keys()
        for cat in value:
            if cat not in valid:
                raise serializers.ValidationError(
                    f"Invalid category '{cat}'. Valid: {', '.join(valid)}"
                )
        return value

    def validate_severity_min(self, value):
        valid = dict(DriftDetection.SEVERITY_CHOICES).keys()
        if value not in valid:
            raise serializers.ValidationError(
                f"Invalid severity '{value}'. Valid: {', '.join(valid)}"
            )
        return value


class DriftAlertRuleListSerializer(DriftAlertRuleSerializer):
    """Lighter serializer for list views."""

    class Meta(DriftAlertRuleSerializer.Meta):
        fields = [
            'id', 'type', 'url',
            'name', 'description', 'organization', 'enabled',
            'severity_min', 'threshold_count',
            'last_triggered_at', 'trigger_count',
            'created', 'modified',
        ]


# ---------------------------------------------------------------------------
# DriftAlert
# ---------------------------------------------------------------------------

class DriftAlertSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = DriftAlert
        fields = [
            'id', 'type', 'url', 'related',
            'created',
            'alert_rule', 'alert_rule_name',
            'host', 'organization',
            'drift_count', 'summary',
            'notification_status', 'notification_error',
        ]
        read_only_fields = fields

    def get_type(self, obj):
        return 'drift_alert'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {}
        if obj.alert_rule_id:
            res['alert_rule'] = f'/api/v2/drift_alert_rules/{obj.alert_rule_id}/'
        if obj.host_id:
            res['host'] = f'/api/v2/hosts/{obj.host_id}/'
        return res


class DriftAlertListSerializer(DriftAlertSerializer):
    """Lighter serializer for list views."""

    class Meta(DriftAlertSerializer.Meta):
        fields = [
            'id', 'type', 'url',
            'created',
            'alert_rule', 'alert_rule_name',
            'host', 'drift_count',
            'notification_status',
        ]


# ---------------------------------------------------------------------------
# DriftSummary (non-model serializer for dashboard)
# ---------------------------------------------------------------------------

class DriftSummarySerializer(serializers.Serializer):
    total_hosts_with_drift = serializers.IntegerField()
    total_drift_items = serializers.IntegerField()
    unacknowledged_count = serializers.IntegerField()
    by_category = serializers.DictField()
    by_severity = serializers.DictField()
