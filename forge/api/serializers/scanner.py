"""IaC Scanner serializers."""

from rest_framework import serializers

from forge.main.models.scanner import Scanner, ScanResult, ScanFinding


class ScannerSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = Scanner
        fields = [
            'id', 'type', 'url', 'related',
            'name', 'description', 'organization',
            'tool', 'config', 'severity_threshold',
            'enforcement', 'enabled', 'applies_to',
            'trigger_count', 'last_run_at', 'last_run_status',
            'created', 'modified',
        ]
        read_only_fields = ['id', 'created', 'modified', 'trigger_count',
                            'last_run_at', 'last_run_status']

    def get_type(self, obj):
        return 'scanner'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {
            'results': f'/api/v2/scan_results/?scanner={obj.pk}',
            'enable': f'/api/v2/scanners/{obj.pk}/enable/',
            'disable': f'/api/v2/scanners/{obj.pk}/disable/',
        }
        if obj.organization_id:
            res['organization'] = f'/api/v2/organizations/{obj.organization_id}/'
        return res


class ScannerListSerializer(ScannerSerializer):
    class Meta(ScannerSerializer.Meta):
        fields = [
            'id', 'type', 'url',
            'name', 'description', 'organization',
            'tool', 'severity_threshold', 'enforcement', 'enabled',
            'applies_to', 'trigger_count', 'last_run_at', 'last_run_status',
            'created', 'modified',
        ]


class ScanFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScanFinding
        fields = ['id', 'rule_id', 'severity', 'file_path', 'line', 'message']
        read_only_fields = fields


class ScanResultSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()
    findings = ScanFindingSerializer(many=True, read_only=True)

    class Meta:
        model = ScanResult
        fields = [
            'id', 'type', 'url', 'related',
            'scanner', 'scanner_name',
            'unified_job', 'unified_job_template',
            'organization', 'triggered_by',
            'status', 'duration_ms', 'finding_count',
            'highest_severity', 'message', 'raw_output',
            'findings', 'created',
        ]
        read_only_fields = fields

    def get_type(self, obj):
        return 'scan_result'

    def get_url(self, obj):
        return obj.get_absolute_url(request=self.context.get('request'))

    def get_related(self, obj):
        res = {}
        if obj.scanner_id:
            res['scanner'] = f'/api/v2/scanners/{obj.scanner_id}/'
        if obj.unified_job_id:
            res['unified_job'] = f'/api/v2/unified_jobs/{obj.unified_job_id}/'
        if obj.unified_job_template_id:
            res['unified_job_template'] = f'/api/v2/unified_job_templates/{obj.unified_job_template_id}/'
        return res


class ScanResultListSerializer(ScanResultSerializer):
    class Meta(ScanResultSerializer.Meta):
        fields = [
            'id', 'type', 'url',
            'scanner', 'scanner_name',
            'unified_job', 'unified_job_template',
            'organization', 'triggered_by',
            'status', 'duration_ms', 'finding_count',
            'highest_severity', 'message', 'created',
        ]
