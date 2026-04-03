"""EDA (Event-Driven Automation) serializers for the Forge API."""

from rest_framework import serializers
from jinja2 import sandbox, TemplateSyntaxError

from forge.main.models.eda import EventRule, EventLog, OutboundWebhook


class EventRuleSerializer(serializers.ModelSerializer):
    webhook_url = serializers.SerializerMethodField()

    class Meta:
        model = EventRule
        fields = [
            'id',
            'type',
            'url',
            'related',
            'created',
            'modified',
            'name',
            'description',
            'organization',
            'enabled',
            'source_type',
            'webhook_path',
            'conditions',
            'actions',
            'throttle_seconds',
            'last_fired_at',
            'fire_count',
            'webhook_url',
        ]
        read_only_fields = ['last_fired_at', 'fire_count', 'created', 'modified']
        extra_kwargs = {
            'webhook_path': {'required': True},
            'actions': {'required': True},
        }

    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    def get_type(self, obj):
        return 'event_rule'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {}
        if obj.organization:
            res['organization'] = f'/api/v2/organizations/{obj.organization_id}/'
        res['event_logs'] = f'/api/v2/event_rules/{obj.pk}/event_logs/'
        res['webhook_key'] = f'/api/v2/event_rules/{obj.pk}/webhook_key/'
        return res

    def get_webhook_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(f'/api/v2/eda_webhooks/{obj.webhook_path}/')
        return f'/api/v2/eda_webhooks/{obj.webhook_path}/'

    def validate_conditions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Conditions must be a list.")
        env = sandbox.ImmutableSandboxedEnvironment()
        for i, condition in enumerate(value):
            if not isinstance(condition, dict):
                raise serializers.ValidationError(f"Condition {i} must be a dict.")
            expr = condition.get('jinja2_expression', '')
            if not expr:
                raise serializers.ValidationError(f"Condition {i} missing 'jinja2_expression'.")
            try:
                env.parse(f'{{% if {expr} %}}ok{{% endif %}}')
            except TemplateSyntaxError as e:
                raise serializers.ValidationError(f"Condition {i} has invalid Jinja2: {e}")
        return value

    def validate_actions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Actions must be a list.")
        if not value:
            raise serializers.ValidationError("At least one action is required.")
        valid_types = dict(EventRule.ACTION_TYPE_CHOICES).keys()
        for i, action in enumerate(value):
            if not isinstance(action, dict):
                raise serializers.ValidationError(f"Action {i} must be a dict.")
            action_type = action.get('action_type', '')
            if action_type not in valid_types:
                raise serializers.ValidationError(
                    f"Action {i} has invalid action_type '{action_type}'. "
                    f"Valid types: {', '.join(valid_types)}"
                )
            if not action.get('target_id'):
                raise serializers.ValidationError(f"Action {i} missing 'target_id'.")
        return value

    def validate_webhook_path(self, value):
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', value):
            raise serializers.ValidationError(
                "webhook_path must contain only letters, numbers, hyphens, and underscores."
            )
        return value


class EventRuleListSerializer(EventRuleSerializer):
    """Lighter serializer for list views."""

    class Meta(EventRuleSerializer.Meta):
        fields = [
            'id',
            'type',
            'url',
            'name',
            'description',
            'organization',
            'enabled',
            'source_type',
            'webhook_path',
            'throttle_seconds',
            'last_fired_at',
            'fire_count',
            'webhook_url',
            'created',
            'modified',
        ]


class EventLogSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = EventLog
        fields = [
            'id',
            'type',
            'url',
            'related',
            'created',
            'event_rule',
            'event_rule_name',
            'source_type',
            'source_ip',
            'event_type',
            'event_guid',
            'payload',
            'headers',
            'conditions_matched',
            'condition_results',
            'actions_triggered',
            'status',
            'error_detail',
            'job_id',
            'organization',
        ]
        read_only_fields = fields

    def get_type(self, obj):
        return 'event_log'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {}
        if obj.event_rule_id:
            res['event_rule'] = f'/api/v2/event_rules/{obj.event_rule_id}/'
        if obj.job_id:
            res['job'] = f'/api/v2/jobs/{obj.job_id}/'
        if obj.organization_id:
            res['organization'] = f'/api/v2/organizations/{obj.organization_id}/'
        return res


class EventLogListSerializer(EventLogSerializer):
    """Lighter serializer for list views — excludes payload and headers."""

    class Meta(EventLogSerializer.Meta):
        fields = [
            'id',
            'type',
            'url',
            'created',
            'event_rule',
            'event_rule_name',
            'source_type',
            'source_ip',
            'event_type',
            'event_guid',
            'conditions_matched',
            'status',
            'error_detail',
            'job_id',
            'organization',
        ]


class OutboundWebhookSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = OutboundWebhook
        fields = [
            'id',
            'type',
            'url',
            'related',
            'created',
            'modified',
            'name',
            'description',
            'organization',
            'target_url',
            'events',
            'custom_headers',
            'enabled',
            'ssl_verify',
            'last_status',
            'last_sent_at',
            'last_error',
        ]
        read_only_fields = ['last_status', 'last_sent_at', 'last_error', 'created', 'modified']

    # Rename 'url' model field to 'target_url' to avoid clash with DRF url field
    target_url = serializers.URLField(source='url')

    def get_type(self, obj):
        return 'outbound_webhook'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {}
        if obj.organization:
            res['organization'] = f'/api/v2/organizations/{obj.organization_id}/'
        return res

    def validate_events(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Events must be a list.")
        if not value:
            raise serializers.ValidationError("At least one event type is required.")
        valid_events = dict(OutboundWebhook.EVENT_CHOICES).keys()
        for event in value:
            if event not in valid_events:
                raise serializers.ValidationError(
                    f"Invalid event type '{event}'. Valid types: {', '.join(valid_events)}"
                )
        return value
