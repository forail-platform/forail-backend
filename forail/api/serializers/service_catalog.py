"""Self-Service Portal serializers."""

from rest_framework import serializers

from forail.main.models.service_catalog import ServiceCatalogItem, ServiceRequest


# ---------------------------------------------------------------------------
# ServiceCatalogItem
# ---------------------------------------------------------------------------

class ServiceCatalogItemSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()
    summary_fields = serializers.SerializerMethodField()
    is_workflow = serializers.BooleanField(read_only=True)

    class Meta:
        model = ServiceCatalogItem
        fields = [
            'id', 'type', 'url', 'related', 'summary_fields',
            'name', 'description', 'icon', 'category', 'tags',
            'organization', 'job_template', 'workflow_job_template',
            'requires_approval', 'approver_team', 'enabled', 'is_workflow',
            'created', 'modified',
        ]
        read_only_fields = ['id', 'created', 'modified', 'is_workflow']

    def get_type(self, obj):
        return 'service_catalog_item'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {}
        if obj.organization_id:
            res['organization'] = f'/api/v2/organizations/{obj.organization_id}/'
        if obj.job_template_id:
            res['job_template'] = f'/api/v2/job_templates/{obj.job_template_id}/'
        if obj.workflow_job_template_id:
            res['workflow_job_template'] = f'/api/v2/workflow_job_templates/{obj.workflow_job_template_id}/'
        if obj.approver_team_id:
            res['approver_team'] = f'/api/v2/teams/{obj.approver_team_id}/'
        res['requests'] = f'/api/v2/service_catalog_items/{obj.pk}/requests/'
        res['launch_data'] = f'/api/v2/service_catalog_items/{obj.pk}/launch_data/'
        res['submit'] = f'/api/v2/service_catalog_items/{obj.pk}/submit/'
        return res

    def get_summary_fields(self, obj):
        res = {}
        if obj.organization:
            res['organization'] = {'id': obj.organization_id, 'name': obj.organization.name}
        tpl = obj.underlying_template
        if tpl is not None:
            res['template'] = {
                'id': tpl.id,
                'name': tpl.name,
                'kind': 'workflow_job_template' if obj.is_workflow else 'job_template',
            }
        if obj.approver_team:
            res['approver_team'] = {'id': obj.approver_team_id, 'name': obj.approver_team.name}
        return res

    def validate(self, attrs):
        jt = attrs.get('job_template') if 'job_template' in attrs else getattr(self.instance, 'job_template', None)
        wf = attrs.get('workflow_job_template') if 'workflow_job_template' in attrs else getattr(self.instance, 'workflow_job_template', None)
        if bool(jt) == bool(wf):
            raise serializers.ValidationError('Exactly one of job_template or workflow_job_template must be set.')
        return attrs


class ServiceCatalogItemListSerializer(ServiceCatalogItemSerializer):
    class Meta(ServiceCatalogItemSerializer.Meta):
        fields = [
            'id', 'type', 'url', 'summary_fields',
            'name', 'description', 'icon', 'category', 'tags',
            'requires_approval', 'enabled', 'is_workflow',
            'created', 'modified',
        ]


# ---------------------------------------------------------------------------
# ServiceRequest
# ---------------------------------------------------------------------------

class ServiceRequestSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()
    summary_fields = serializers.SerializerMethodField()

    class Meta:
        model = ServiceRequest
        fields = [
            'id', 'type', 'url', 'related', 'summary_fields',
            'catalog_item', 'requested_by', 'status',
            'extra_vars', 'node_survey_data', 'justification',
            'approved_by', 'approved_at', 'rejection_reason',
            'unified_job', 'created', 'modified',
        ]
        read_only_fields = [
            'id', 'requested_by', 'status', 'approved_by', 'approved_at',
            'rejection_reason', 'unified_job', 'created', 'modified',
        ]

    def get_type(self, obj):
        return 'service_request'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {
            'catalog_item': f'/api/v2/service_catalog_items/{obj.catalog_item_id}/',
        }
        if obj.requested_by_id:
            res['requested_by'] = f'/api/v2/users/{obj.requested_by_id}/'
        if obj.approved_by_id:
            res['approved_by'] = f'/api/v2/users/{obj.approved_by_id}/'
        if obj.unified_job_id:
            res['unified_job'] = f'/api/v2/unified_jobs/{obj.unified_job_id}/'
        if obj.status == 'pending_approval':
            res['approve'] = f'/api/v2/service_requests/{obj.pk}/approve/'
            res['reject'] = f'/api/v2/service_requests/{obj.pk}/reject/'
        return res

    def get_summary_fields(self, obj):
        res = {}
        ci = obj.catalog_item
        res['catalog_item'] = {
            'id': ci.id, 'name': ci.name, 'icon': ci.icon, 'category': ci.category,
        }
        if obj.requested_by:
            res['requested_by'] = {
                'id': obj.requested_by_id,
                'username': obj.requested_by.username,
            }
        if obj.approved_by:
            res['approved_by'] = {
                'id': obj.approved_by_id,
                'username': obj.approved_by.username,
            }
        if obj.unified_job_id:
            res['unified_job'] = {
                'id': obj.unified_job_id,
                'status': obj.unified_job.status if obj.unified_job else None,
            }
        return res


class ServiceRequestListSerializer(ServiceRequestSerializer):
    class Meta(ServiceRequestSerializer.Meta):
        fields = [
            'id', 'type', 'url', 'summary_fields',
            'catalog_item', 'status', 'requested_by',
            'created', 'modified',
        ]


class ServiceRequestSubmitSerializer(serializers.Serializer):
    extra_vars = serializers.JSONField(required=False, default=dict)
    node_survey_data = serializers.JSONField(required=False, default=dict)
    justification = serializers.CharField(required=False, allow_blank=True, default='')


class ServiceRequestRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')
