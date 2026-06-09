"""Policy-as-Code serializers."""

from rest_framework import serializers

from forail.main.models.policy import Policy, PolicyDecision


class PolicySerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = Policy
        fields = [
            'id', 'type', 'url', 'related',
            'name', 'description', 'organization',
            'rego_module', 'package_path',
            'enforcement', 'enabled', 'applies_to',
            'trigger_count', 'last_triggered_at', 'last_evaluated_at',
            'last_sync_status',
            'created', 'modified',
        ]
        read_only_fields = ['id', 'created', 'modified', 'trigger_count',
                            'last_triggered_at', 'last_evaluated_at', 'last_sync_status']

    def get_type(self, obj):
        return 'policy'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {
            'decisions': f'/api/v2/policy_decisions/?policy={obj.pk}',
            'enable': f'/api/v2/policies/{obj.pk}/enable/',
            'disable': f'/api/v2/policies/{obj.pk}/disable/',
            'test': f'/api/v2/policies/{obj.pk}/test/',
        }
        if obj.organization_id:
            res['organization'] = f'/api/v2/organizations/{obj.organization_id}/'
        return res


class PolicyListSerializer(PolicySerializer):
    class Meta(PolicySerializer.Meta):
        fields = [
            'id', 'type', 'url',
            'name', 'description', 'organization',
            'enforcement', 'enabled', 'applies_to',
            'trigger_count', 'last_triggered_at', 'last_sync_status',
            'created', 'modified',
        ]


class PolicyDecisionSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = PolicyDecision
        fields = [
            'id', 'type', 'url', 'related',
            'policy', 'policy_name', 'decision',
            'unified_job', 'unified_job_template',
            'organization', 'triggered_by',
            'message', 'context', 'created',
        ]
        read_only_fields = fields

    def get_type(self, obj):
        return 'policy_decision'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {}
        if obj.policy_id:
            res['policy'] = f'/api/v2/policies/{obj.policy_id}/'
        if obj.unified_job_id:
            res['unified_job'] = f'/api/v2/unified_jobs/{obj.unified_job_id}/'
        if obj.unified_job_template_id:
            res['unified_job_template'] = f'/api/v2/unified_job_templates/{obj.unified_job_template_id}/'
        return res


class PolicyDecisionListSerializer(PolicyDecisionSerializer):
    class Meta(PolicyDecisionSerializer.Meta):
        fields = [
            'id', 'type', 'url',
            'policy', 'policy_name', 'decision',
            'unified_job', 'unified_job_template',
            'organization', 'triggered_by',
            'message', 'created',
        ]


class PolicyTestSerializer(serializers.Serializer):
    input = serializers.JSONField(required=True)
