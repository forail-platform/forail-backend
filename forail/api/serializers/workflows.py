# Copyright (c) 2015 Ansible, Inc.
# Copyright (c) 2026 Krstan Vjestica / Forail Project
# All Rights Reserved.

"""Workflow serializers for the Forail API."""

import json
from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import ValidationError
from rest_framework import serializers

from ansible_base.lib.utils.models import get_type_for_model

from forail.main.models import (
    Credential,
    ExecutionEnvironment,
    InstanceGroup,
    Inventory,
    InventorySource,
    JobTemplate,
    Label,
    Organization,
    Project,
    UnifiedJobTemplate,
    WorkflowApproval,
    WorkflowApprovalTemplate,
    WorkflowJob,
    WorkflowJobNode,
    WorkflowJobTemplate,
    WorkflowJobTemplateNode,
)
from forail.main.models.base import VERBOSITY_CHOICES, NEW_JOB_TYPE_CHOICES
from forail.main.utils import (
    getattrd,
    parse_yaml_or_json,
    encrypt_dict,
)
from forail.main.redact import REPLACE_STR
from forail.main.validators import vars_validate_or_raise
from forail.api.fields import VerbatimField
from forail.api.serializers.base import (
    BaseSerializer,
    LabelsListMixin,
)
from forail.api.serializers.unified import (
    UnifiedJobTemplateSerializer,
    UnifiedJobSerializer,
    UnifiedJobListSerializer,
)
from forail.api.serializers.jobs import JobTemplateMixin


class WorkflowJobTemplateSerializer(JobTemplateMixin, LabelsListMixin, UnifiedJobTemplateSerializer):
    show_capabilities = ['start', 'schedule', 'edit', 'copy', 'delete']
    capabilities_prefetch = ['admin', 'execute', {'copy': 'organization.workflow_admin'}]
    limit = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)
    scm_branch = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)

    skip_tags = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)
    job_tags = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)

    class Meta:
        model = WorkflowJobTemplate
        fields = (
            '*',
            'extra_vars',
            'organization',
            'survey_enabled',
            'allow_simultaneous',
            'ask_variables_on_launch',
            'inventory',
            'limit',
            'scm_branch',
            'ask_inventory_on_launch',
            'ask_scm_branch_on_launch',
            'ask_limit_on_launch',
            'webhook_service',
            'webhook_credential',
            '-execution_environment',
            'ask_labels_on_launch',
            'ask_skip_tags_on_launch',
            'ask_tags_on_launch',
            'skip_tags',
            'job_tags',
        )

    def get_related(self, obj):
        res = super(WorkflowJobTemplateSerializer, self).get_related(obj)
        res.update(
            workflow_jobs=self.reverse('api:workflow_job_template_jobs_list', kwargs={'pk': obj.pk}),
            schedules=self.reverse('api:workflow_job_template_schedules_list', kwargs={'pk': obj.pk}),
            launch=self.reverse('api:workflow_job_template_launch', kwargs={'pk': obj.pk}),
            webhook_key=self.reverse('api:webhook_key', kwargs={'model_kwarg': 'workflow_job_templates', 'pk': obj.pk}),
            webhook_receiver=(
                self.reverse('api:webhook_receiver_{}'.format(obj.webhook_service), kwargs={'model_kwarg': 'workflow_job_templates', 'pk': obj.pk})
                if obj.webhook_service
                else ''
            ),
            workflow_nodes=self.reverse('api:workflow_job_template_workflow_nodes_list', kwargs={'pk': obj.pk}),
            labels=self.reverse('api:workflow_job_template_label_list', kwargs={'pk': obj.pk}),
            activity_stream=self.reverse('api:workflow_job_template_activity_stream_list', kwargs={'pk': obj.pk}),
            notification_templates_started=self.reverse('api:workflow_job_template_notification_templates_started_list', kwargs={'pk': obj.pk}),
            notification_templates_success=self.reverse('api:workflow_job_template_notification_templates_success_list', kwargs={'pk': obj.pk}),
            notification_templates_error=self.reverse('api:workflow_job_template_notification_templates_error_list', kwargs={'pk': obj.pk}),
            notification_templates_approvals=self.reverse('api:workflow_job_template_notification_templates_approvals_list', kwargs={'pk': obj.pk}),
            access_list=self.reverse('api:workflow_job_template_access_list', kwargs={'pk': obj.pk}),
            object_roles=self.reverse('api:workflow_job_template_object_roles_list', kwargs={'pk': obj.pk}),
            survey_spec=self.reverse('api:workflow_job_template_survey_spec', kwargs={'pk': obj.pk}),
            copy=self.reverse('api:workflow_job_template_copy', kwargs={'pk': obj.pk}),
        )
        res.pop('execution_environment', None)  # EEs aren't meaningful for workflows
        if obj.organization:
            res['organization'] = self.reverse('api:organization_detail', kwargs={'pk': obj.organization.pk})
        if obj.webhook_credential_id:
            res['webhook_credential'] = self.reverse('api:credential_detail', kwargs={'pk': obj.webhook_credential_id})
        if obj.inventory_id:
            res['inventory'] = self.reverse('api:inventory_detail', kwargs={'pk': obj.inventory_id})
        return res

    def validate_extra_vars(self, value):
        return vars_validate_or_raise(value)

    def validate(self, attrs):
        attrs = super(WorkflowJobTemplateSerializer, self).validate(attrs)

        # process char_prompts, these are not direct fields on the model
        mock_obj = self.Meta.model()
        for field_name in ('scm_branch', 'limit', 'skip_tags', 'job_tags'):
            if field_name in attrs:
                setattr(mock_obj, field_name, attrs[field_name])
                attrs.pop(field_name)

        # Model `.save` needs the container dict, not the pseudo fields
        if mock_obj.char_prompts:
            attrs['char_prompts'] = mock_obj.char_prompts

        return attrs


class WorkflowJobTemplateWithSpecSerializer(WorkflowJobTemplateSerializer):
    """
    Used for activity stream entries.
    """

    class Meta:
        model = WorkflowJobTemplate
        fields = ('*', 'survey_spec')


class WorkflowJobSerializer(LabelsListMixin, UnifiedJobSerializer):
    limit = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)
    scm_branch = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)

    skip_tags = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)
    job_tags = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)

    class Meta:
        model = WorkflowJob
        fields = (
            '*',
            'workflow_job_template',
            'extra_vars',
            'allow_simultaneous',
            'job_template',
            'is_sliced_job',
            '-execution_environment',
            '-execution_node',
            '-event_processing_finished',
            '-controller_node',
            'inventory',
            'limit',
            'scm_branch',
            'webhook_service',
            'webhook_credential',
            'webhook_guid',
            'skip_tags',
            'job_tags',
        )

    def get_related(self, obj):
        res = super(WorkflowJobSerializer, self).get_related(obj)
        res.pop('execution_environment', None)  # EEs aren't meaningful for workflows
        if obj.workflow_job_template:
            res['workflow_job_template'] = self.reverse('api:workflow_job_template_detail', kwargs={'pk': obj.workflow_job_template.pk})
            res['notifications'] = self.reverse('api:workflow_job_notifications_list', kwargs={'pk': obj.pk})
        if obj.job_template_id:
            res['job_template'] = self.reverse('api:job_template_detail', kwargs={'pk': obj.job_template_id})
        res['workflow_nodes'] = self.reverse('api:workflow_job_workflow_nodes_list', kwargs={'pk': obj.pk})
        res['labels'] = self.reverse('api:workflow_job_label_list', kwargs={'pk': obj.pk})
        res['activity_stream'] = self.reverse('api:workflow_job_activity_stream_list', kwargs={'pk': obj.pk})
        res['relaunch'] = self.reverse('api:workflow_job_relaunch', kwargs={'pk': obj.pk})
        if obj.can_cancel or True:
            res['cancel'] = self.reverse('api:workflow_job_cancel', kwargs={'pk': obj.pk})
        return res

    def to_representation(self, obj):
        ret = super(WorkflowJobSerializer, self).to_representation(obj)
        if obj is None:
            return ret
        if 'extra_vars' in ret:
            ret['extra_vars'] = obj.display_extra_vars()
        return ret


class WorkflowJobListSerializer(WorkflowJobSerializer, UnifiedJobListSerializer):
    class Meta:
        fields = ('*', '-execution_environment', '-execution_node', '-controller_node')


class WorkflowJobCancelSerializer(WorkflowJobSerializer):
    can_cancel = serializers.BooleanField(read_only=True)

    class Meta:
        fields = ('can_cancel',)


class WorkflowApprovalViewSerializer(UnifiedJobSerializer):
    class Meta:
        model = WorkflowApproval
        fields = []


class WorkflowApprovalSerializer(UnifiedJobSerializer):
    can_approve_or_deny = serializers.SerializerMethodField()
    approval_expiration = serializers.SerializerMethodField()
    timed_out = serializers.ReadOnlyField()

    class Meta:
        model = WorkflowApproval
        fields = ('*', '-controller_node', '-execution_node', 'can_approve_or_deny', 'approval_expiration', 'timed_out')

    def get_approval_expiration(self, obj):
        if obj.status != 'pending' or obj.timeout == 0:
            return None
        return obj.created + timedelta(seconds=obj.timeout)

    def get_can_approve_or_deny(self, obj):
        request = self.context.get('request', None)
        allowed = request.user.can_access(WorkflowApproval, 'approve_or_deny', obj)
        return allowed is True and obj.status == 'pending'

    def get_related(self, obj):
        res = super(WorkflowApprovalSerializer, self).get_related(obj)

        if obj.workflow_approval_template:
            res['workflow_approval_template'] = self.reverse('api:workflow_approval_template_detail', kwargs={'pk': obj.workflow_approval_template.pk})
        res['approve'] = self.reverse('api:workflow_approval_approve', kwargs={'pk': obj.pk})
        res['deny'] = self.reverse('api:workflow_approval_deny', kwargs={'pk': obj.pk})
        if obj.approved_or_denied_by:
            res['approved_or_denied_by'] = self.reverse('api:user_detail', kwargs={'pk': obj.approved_or_denied_by.pk})
        return res


class WorkflowApprovalActivityStreamSerializer(WorkflowApprovalSerializer):
    """
    timed_out and status are usually read-only fields
    However, when we generate an activity stream record, we *want* to record
    these types of changes.  This serializer allows us to do so.
    """

    status = serializers.ChoiceField(choices=JobTemplate.JOB_TEMPLATE_STATUS_CHOICES)
    timed_out = serializers.BooleanField()


class WorkflowApprovalListSerializer(WorkflowApprovalSerializer, UnifiedJobListSerializer):
    class Meta:
        fields = ('*', '-controller_node', '-execution_node', 'can_approve_or_deny', 'approval_expiration', 'timed_out')


class WorkflowApprovalTemplateSerializer(UnifiedJobTemplateSerializer):
    class Meta:
        model = WorkflowApprovalTemplate
        fields = ('*', 'timeout', 'name')

    def get_related(self, obj):
        res = super(WorkflowApprovalTemplateSerializer, self).get_related(obj)
        if 'last_job' in res:
            del res['last_job']

        res.update(jobs=self.reverse('api:workflow_approval_template_jobs_list', kwargs={'pk': obj.pk}))
        return res


class LaunchConfigurationBaseSerializer(BaseSerializer):
    scm_branch = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)
    job_type = serializers.ChoiceField(allow_blank=True, allow_null=True, required=False, default=None, choices=NEW_JOB_TYPE_CHOICES)
    job_tags = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)
    limit = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)
    skip_tags = serializers.CharField(allow_blank=True, allow_null=True, required=False, default=None)
    diff_mode = serializers.BooleanField(required=False, allow_null=True, default=None)
    verbosity = serializers.ChoiceField(allow_null=True, required=False, default=None, choices=VERBOSITY_CHOICES)
    forks = serializers.IntegerField(required=False, allow_null=True, min_value=0, default=None)
    job_slice_count = serializers.IntegerField(required=False, allow_null=True, min_value=0, default=None)
    timeout = serializers.IntegerField(required=False, allow_null=True, default=None)
    exclude_errors = ()

    class Meta:
        fields = (
            '*',
            'extra_data',
            'inventory',  # Saved launch-time config fields
            'scm_branch',
            'job_type',
            'job_tags',
            'skip_tags',
            'limit',
            'skip_tags',
            'diff_mode',
            'verbosity',
            'execution_environment',
            'forks',
            'job_slice_count',
            'timeout',
        )

    def get_related(self, obj):
        res = super(LaunchConfigurationBaseSerializer, self).get_related(obj)
        if obj.inventory_id:
            res['inventory'] = self.reverse('api:inventory_detail', kwargs={'pk': obj.inventory_id})
        if obj.execution_environment_id:
            res['execution_environment'] = self.reverse('api:execution_environment_detail', kwargs={'pk': obj.execution_environment_id})
        res['labels'] = self.reverse('api:{}_labels_list'.format(get_type_for_model(self.Meta.model)), kwargs={'pk': obj.pk})
        res['credentials'] = self.reverse('api:{}_credentials_list'.format(get_type_for_model(self.Meta.model)), kwargs={'pk': obj.pk})
        res['instance_groups'] = self.reverse('api:{}_instance_groups_list'.format(get_type_for_model(self.Meta.model)), kwargs={'pk': obj.pk})
        return res

    def _build_mock_obj(self, attrs):
        mock_obj = self.Meta.model()
        if self.instance:
            for field in self.instance._meta.fields:
                setattr(mock_obj, field.name, getattr(self.instance, field.name))
        field_names = set(field.name for field in self.Meta.model._meta.fields)
        for field_name, value in list(attrs.items()):
            setattr(mock_obj, field_name, value)
            if field_name not in field_names:
                attrs.pop(field_name)
        return mock_obj

    def to_representation(self, obj):
        ret = super(LaunchConfigurationBaseSerializer, self).to_representation(obj)
        if obj is None:
            return ret
        if 'extra_data' in ret and obj.survey_passwords:
            ret['extra_data'] = obj.display_extra_vars()
        return ret

    def validate(self, attrs):
        db_extra_data = {}
        if self.instance:
            db_extra_data = parse_yaml_or_json(self.instance.extra_data)

        attrs = super(LaunchConfigurationBaseSerializer, self).validate(attrs)

        ujt = None
        if 'unified_job_template' in attrs:
            ujt = attrs['unified_job_template']
        elif self.instance:
            ujt = self.instance.unified_job_template
        if ujt is None:
            ret = {}
            for fd in ('workflow_job_template', 'identifier', 'all_parents_must_converge'):
                if fd in attrs:
                    ret[fd] = attrs[fd]
            return ret

        # build additional field survey_passwords to track redacted variables
        password_dict = {}
        extra_data = parse_yaml_or_json(attrs.get('extra_data', {}))
        if hasattr(ujt, 'survey_password_variables'):
            # Prepare additional field survey_passwords for save
            for key in ujt.survey_password_variables():
                if key in extra_data:
                    password_dict[key] = REPLACE_STR

        # Replace $encrypted$ submissions with db value if exists
        if 'extra_data' in attrs:
            if password_dict:
                if not self.instance or password_dict != self.instance.survey_passwords:
                    attrs['survey_passwords'] = password_dict.copy()
                # Force dict type (cannot preserve YAML formatting if passwords are involved)
                # Encrypt the extra_data for save, only current password vars in JT survey
                # but first, make a copy or else this is referenced by request.data, and
                # user could get encrypted string in form data in API browser
                attrs['extra_data'] = extra_data.copy()
                encrypt_dict(attrs['extra_data'], password_dict.keys())
                # For any raw $encrypted$ string, either
                # - replace with existing DB value
                # - raise a validation error
                # - ignore, if default present
                for key in password_dict.keys():
                    if attrs['extra_data'].get(key, None) == REPLACE_STR:
                        if key not in db_extra_data:
                            element = ujt.pivot_spec(ujt.survey_spec)[key]
                            # NOTE: validation _of_ the default values of password type
                            # questions not done here or on launch, but doing so could
                            # leak info about values, so it should not be added
                            if not ('default' in element and element['default']):
                                raise serializers.ValidationError({"extra_data": _('Provided variable {} has no database value to replace with.').format(key)})
                        else:
                            attrs['extra_data'][key] = db_extra_data[key]

        # Build unsaved version of this config, use it to detect prompts errors
        mock_obj = self._build_mock_obj(attrs)
        if set(list(ujt.get_ask_mapping().keys()) + ['extra_data']) & set(attrs.keys()):
            accepted, rejected, errors = ujt._accept_or_ignore_job_kwargs(_exclude_errors=self.exclude_errors, **mock_obj.prompts_dict())
        else:
            # Only perform validation of prompts if prompts fields are provided
            errors = {}

        # Remove all unprocessed $encrypted$ strings, indicating default usage
        if 'extra_data' in attrs and password_dict:
            for key, value in attrs['extra_data'].copy().items():
                if value == REPLACE_STR:
                    if key in password_dict:
                        attrs['extra_data'].pop(key)
                        attrs.get('survey_passwords', {}).pop(key, None)
                    else:
                        errors.setdefault('extra_vars', []).append(_('"$encrypted$ is a reserved keyword, may not be used for {}."'.format(key)))

        # Launch configs call extra_vars extra_data for historical reasons
        if 'extra_vars' in errors:
            errors['extra_data'] = errors.pop('extra_vars')
        if errors:
            raise serializers.ValidationError(errors)

        # Model `.save` needs the container dict, not the pseudo fields
        if mock_obj.char_prompts:
            attrs['char_prompts'] = mock_obj.char_prompts

        return attrs


class WorkflowJobTemplateNodeSerializer(LaunchConfigurationBaseSerializer):
    success_nodes = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    failure_nodes = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    always_nodes = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    exclude_errors = ('required',)  # required variables may be provided by WFJT or on launch

    class Meta:
        model = WorkflowJobTemplateNode
        fields = (
            '*',
            'workflow_job_template',
            '-name',
            '-description',
            'id',
            'url',
            'related',
            'unified_job_template',
            'success_nodes',
            'failure_nodes',
            'always_nodes',
            'all_parents_must_converge',
            'identifier',
            'survey_enabled',
            'survey_spec',
        )

    def get_related(self, obj):
        res = super(WorkflowJobTemplateNodeSerializer, self).get_related(obj)
        res['create_approval_template'] = self.reverse('api:workflow_job_template_node_create_approval', kwargs={'pk': obj.pk})
        res['success_nodes'] = self.reverse('api:workflow_job_template_node_success_nodes_list', kwargs={'pk': obj.pk})
        res['failure_nodes'] = self.reverse('api:workflow_job_template_node_failure_nodes_list', kwargs={'pk': obj.pk})
        res['always_nodes'] = self.reverse('api:workflow_job_template_node_always_nodes_list', kwargs={'pk': obj.pk})
        if obj.unified_job_template:
            res['unified_job_template'] = obj.unified_job_template.get_absolute_url(self.context.get('request'))
        try:
            res['workflow_job_template'] = self.reverse('api:workflow_job_template_detail', kwargs={'pk': obj.workflow_job_template.pk})
        except WorkflowJobTemplate.DoesNotExist:
            pass
        return res

    def build_relational_field(self, field_name, relation_info):
        field_class, field_kwargs = super(WorkflowJobTemplateNodeSerializer, self).build_relational_field(field_name, relation_info)
        # workflow_job_template is read-only unless creating a new node.
        if self.instance and field_name == 'workflow_job_template':
            field_kwargs['read_only'] = True
            field_kwargs.pop('queryset', None)
        return field_class, field_kwargs

    def get_summary_fields(self, obj):
        summary_fields = super(WorkflowJobTemplateNodeSerializer, self).get_summary_fields(obj)
        if isinstance(obj.unified_job_template, WorkflowApprovalTemplate):
            summary_fields['unified_job_template']['timeout'] = obj.unified_job_template.timeout
        return summary_fields


class WorkflowJobNodeSerializer(LaunchConfigurationBaseSerializer):
    success_nodes = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    failure_nodes = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    always_nodes = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = WorkflowJobNode
        fields = (
            '*',
            'job',
            'workflow_job',
            '-name',
            '-description',
            'id',
            'url',
            'related',
            'unified_job_template',
            'success_nodes',
            'failure_nodes',
            'always_nodes',
            'all_parents_must_converge',
            'do_not_run',
            'identifier',
        )

    def get_related(self, obj):
        res = super(WorkflowJobNodeSerializer, self).get_related(obj)
        res['success_nodes'] = self.reverse('api:workflow_job_node_success_nodes_list', kwargs={'pk': obj.pk})
        res['failure_nodes'] = self.reverse('api:workflow_job_node_failure_nodes_list', kwargs={'pk': obj.pk})
        res['always_nodes'] = self.reverse('api:workflow_job_node_always_nodes_list', kwargs={'pk': obj.pk})
        if obj.unified_job_template:
            res['unified_job_template'] = obj.unified_job_template.get_absolute_url(self.context.get('request'))
        if obj.job:
            res['job'] = obj.job.get_absolute_url(self.context.get('request'))
        if obj.workflow_job:
            res['workflow_job'] = self.reverse('api:workflow_job_detail', kwargs={'pk': obj.workflow_job.pk})
        return res

    def get_summary_fields(self, obj):
        summary_fields = super(WorkflowJobNodeSerializer, self).get_summary_fields(obj)
        if isinstance(obj.job, WorkflowApproval):
            summary_fields['job']['timed_out'] = obj.job.timed_out
        return summary_fields


class WorkflowJobNodeListSerializer(WorkflowJobNodeSerializer):
    pass


class WorkflowJobNodeDetailSerializer(WorkflowJobNodeSerializer):
    pass


class WorkflowJobTemplateNodeDetailSerializer(WorkflowJobTemplateNodeSerializer):
    """
    Influence the api browser sample data to not include workflow_job_template
    when editing a WorkflowNode.

    Note: I was not able to accomplish this through the use of extra_kwargs.
    Maybe something to do with workflow_job_template being a relational field?
    """

    def build_relational_field(self, field_name, relation_info):
        field_class, field_kwargs = super(WorkflowJobTemplateNodeDetailSerializer, self).build_relational_field(field_name, relation_info)
        if self.instance and field_name == 'workflow_job_template':
            field_kwargs['read_only'] = True
            field_kwargs.pop('queryset', None)
        return field_class, field_kwargs


class WorkflowJobTemplateNodeCreateApprovalSerializer(BaseSerializer):
    class Meta:
        model = WorkflowApprovalTemplate
        fields = ('timeout', 'name', 'description')

    def to_representation(self, obj):
        return {}


class WorkflowJobLaunchSerializer(BaseSerializer):
    can_start_without_user_input = serializers.BooleanField(read_only=True)
    defaults = serializers.SerializerMethodField()
    variables_needed_to_start = serializers.ReadOnlyField()
    survey_enabled = serializers.SerializerMethodField()
    extra_vars = VerbatimField(required=False, write_only=True)
    inventory = serializers.PrimaryKeyRelatedField(queryset=Inventory.objects.all(), required=False, write_only=True)
    limit = serializers.CharField(required=False, write_only=True, allow_blank=True)
    scm_branch = serializers.CharField(required=False, write_only=True, allow_blank=True)
    workflow_job_template_data = serializers.SerializerMethodField()
    node_surveys = serializers.SerializerMethodField()
    node_survey_data = serializers.JSONField(required=False, write_only=True, default=dict)

    labels = serializers.PrimaryKeyRelatedField(many=True, queryset=Label.objects.all(), required=False, write_only=True)
    skip_tags = serializers.CharField(required=False, write_only=True, allow_blank=True)
    job_tags = serializers.CharField(required=False, write_only=True, allow_blank=True)

    class Meta:
        model = WorkflowJobTemplate
        fields = (
            'ask_inventory_on_launch',
            'ask_limit_on_launch',
            'ask_scm_branch_on_launch',
            'can_start_without_user_input',
            'defaults',
            'extra_vars',
            'inventory',
            'limit',
            'scm_branch',
            'survey_enabled',
            'variables_needed_to_start',
            'node_templates_missing',
            'node_prompts_rejected',
            'workflow_job_template_data',
            'survey_enabled',
            'ask_variables_on_launch',
            'ask_labels_on_launch',
            'labels',
            'ask_skip_tags_on_launch',
            'ask_tags_on_launch',
            'skip_tags',
            'job_tags',
            'node_surveys',
            'node_survey_data',
        )
        read_only_fields = (
            'ask_inventory_on_launch',
            'ask_variables_on_launch',
            'ask_skip_tags_on_launch',
            'ask_labels_on_launch',
            'ask_limit_on_launch',
            'ask_scm_branch_on_launch',
            'ask_tags_on_launch',
        )

    def get_survey_enabled(self, obj):
        if obj:
            return obj.survey_enabled and 'spec' in obj.survey_spec
        return False

    def get_defaults(self, obj):
        defaults_dict = {}
        for field_name in WorkflowJobTemplate.get_ask_mapping().keys():
            if field_name == 'inventory':
                defaults_dict[field_name] = dict(name=getattrd(obj, '%s.name' % field_name, None), id=getattrd(obj, '%s.pk' % field_name, None))
            elif field_name == 'labels':
                for label in obj.labels.all():
                    label_dict = {"id": label.id, "name": label.name}
                    defaults_dict.setdefault(field_name, []).append(label_dict)
            else:
                defaults_dict[field_name] = getattr(obj, field_name)
        return defaults_dict

    def get_workflow_job_template_data(self, obj):
        return dict(name=obj.name, id=obj.id, description=obj.description)

    def get_node_surveys(self, obj):
        """Return survey specs for all nodes that have surveys enabled."""
        result = []
        for node in obj.workflow_job_template_nodes.filter(survey_enabled=True).select_related('unified_job_template'):
            spec = node.survey_spec
            if not isinstance(spec, dict) or 'spec' not in spec:
                continue
            template_name = ''
            if node.unified_job_template:
                template_name = node.unified_job_template.name
            result.append({
                'node_id': node.pk,
                'identifier': node.identifier,
                'node_name': template_name,
                'survey_spec': spec,
            })
        return result

    def validate(self, attrs):
        template = self.instance

        accepted, rejected, errors = template._accept_or_ignore_job_kwargs(**attrs)
        self._ignored_fields = rejected

        if template.inventory and template.inventory.pending_deletion is True:
            errors['inventory'] = _("The inventory associated with this Workflow is being deleted.")
        elif 'inventory' in accepted and accepted['inventory'].pending_deletion:
            errors['inventory'] = _("The provided inventory is being deleted.")

        if errors:
            raise serializers.ValidationError(errors)

        WFJT_extra_vars = template.extra_vars
        WFJT_inventory = template.inventory
        WFJT_limit = template.limit
        WFJT_scm_branch = template.scm_branch

        super(WorkflowJobLaunchSerializer, self).validate(attrs)
        template.extra_vars = WFJT_extra_vars
        template.inventory = WFJT_inventory
        template.limit = WFJT_limit
        template.scm_branch = WFJT_scm_branch

        return accepted


class BulkJobNodeSerializer(WorkflowJobNodeSerializer):
    # We don't do a PrimaryKeyRelatedField for unified_job_template and others, because that increases the number
    # of database queries, rather we take them as integer and later convert them to objects in get_objectified_jobs
    unified_job_template = serializers.IntegerField(
        required=True, min_value=1, help_text=_('Primary key of the template for this job, can be a job template or inventory source.')
    )
    inventory = serializers.IntegerField(required=False, min_value=1)
    execution_environment = serializers.IntegerField(required=False, min_value=1)
    # many-to-many fields
    credentials = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)
    labels = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)
    instance_groups = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)

    class Meta:
        model = WorkflowJobNode
        fields = ('*', 'credentials', 'labels', 'instance_groups')  # m2m fields are not canonical for WJ nodes

    def validate(self, attrs):
        return super(LaunchConfigurationBaseSerializer, self).validate(attrs)

    def get_validation_exclusions(self, obj=None):
        ret = super().get_validation_exclusions(obj)
        ret.extend(['unified_job_template', 'inventory', 'execution_environment'])
        return ret


class BulkJobLaunchSerializer(serializers.Serializer):
    name = serializers.CharField(default='Bulk Job Launch', max_length=512, write_only=True, required=False, allow_blank=True)  # limited by max name of jobs
    jobs = BulkJobNodeSerializer(
        many=True,
        allow_empty=False,
        write_only=True,
        max_length=100000,
        help_text=_('List of jobs to be launched, JSON. e.g. [{"unified_job_template": 7}, {"unified_job_template": 10}]'),
    )
    description = serializers.CharField(write_only=True, required=False, allow_blank=False)
    extra_vars = serializers.JSONField(write_only=True, required=False)
    organization = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(),
        required=False,
        default=None,
        allow_null=True,
        write_only=True,
        help_text=_('Inherit permissions from this organization. If not provided, a organization the user is a member of will be selected automatically.'),
    )
    inventory = serializers.PrimaryKeyRelatedField(queryset=Inventory.objects.all(), required=False, write_only=True)
    limit = serializers.CharField(write_only=True, required=False, allow_blank=False)
    scm_branch = serializers.CharField(write_only=True, required=False, allow_blank=False)
    skip_tags = serializers.CharField(write_only=True, required=False, allow_blank=False)
    job_tags = serializers.CharField(write_only=True, required=False, allow_blank=False)

    class Meta:
        model = WorkflowJob
        fields = ('name', 'jobs', 'description', 'extra_vars', 'organization', 'inventory', 'limit', 'scm_branch', 'skip_tags', 'job_tags')
        read_only_fields = ()

    def validate(self, attrs):
        request = self.context.get('request', None)
        identifiers = set()
        if len(attrs['jobs']) > settings.BULK_JOB_MAX_LAUNCH:
            raise serializers.ValidationError(_('Number of requested jobs exceeds system setting BULK_JOB_MAX_LAUNCH'))

        for node in attrs['jobs']:
            if 'identifier' in node:
                if node['identifier'] in identifiers:
                    raise serializers.ValidationError(_(f"Identifier {node['identifier']} not unique"))
                identifiers.add(node['identifier'])
            else:
                node['identifier'] = str(uuid4())

        requested_ujts = {j['unified_job_template'] for j in attrs['jobs']}
        requested_use_inventories = {job['inventory'] for job in attrs['jobs'] if 'inventory' in job}
        requested_use_execution_environments = {job['execution_environment'] for job in attrs['jobs'] if 'execution_environment' in job}
        requested_use_credentials = set()
        requested_use_labels = set()
        requested_use_instance_groups = set()
        for job in attrs['jobs']:
            for cred in job.get('credentials', []):
                requested_use_credentials.add(cred)
            for label in job.get('labels', []):
                requested_use_labels.add(label)
            for instance_group in job.get('instance_groups', []):
                requested_use_instance_groups.add(instance_group)

        key_to_obj_map = {
            "unified_job_template": {obj.id: obj for obj in UnifiedJobTemplate.objects.filter(id__in=requested_ujts)},
            "inventory": {obj.id: obj for obj in Inventory.objects.filter(id__in=requested_use_inventories)},
            "credentials": {obj.id: obj for obj in Credential.objects.filter(id__in=requested_use_credentials)},
            "labels": {obj.id: obj for obj in Label.objects.filter(id__in=requested_use_labels)},
            "instance_groups": {obj.id: obj for obj in InstanceGroup.objects.filter(id__in=requested_use_instance_groups)},
            "execution_environment": {obj.id: obj for obj in ExecutionEnvironment.objects.filter(id__in=requested_use_execution_environments)},
        }

        ujts = {}
        for ujt in key_to_obj_map['unified_job_template'].values():
            ujts.setdefault(type(ujt), [])
            ujts[type(ujt)].append(ujt)

        unallowed_types = set(ujts.keys()) - set([JobTemplate, Project, InventorySource, WorkflowJobTemplate])
        if unallowed_types:
            type_names = ' '.join([cls._meta.verbose_name.title() for cls in unallowed_types])
            raise serializers.ValidationError(_("Template types {type_names} not allowed in bulk jobs").format(type_names=type_names))

        for model, obj_list in ujts.items():
            role_field = 'execute_role' if issubclass(model, (JobTemplate, WorkflowJobTemplate)) else 'update_role'
            self.check_list_permission(model, set([obj.id for obj in obj_list]), role_field)

        self.check_organization_permission(attrs, request)

        if 'inventory' in attrs:
            requested_use_inventories.add(attrs['inventory'].id)

        self.check_list_permission(Inventory, requested_use_inventories, 'use_role')

        self.check_list_permission(Credential, requested_use_credentials, 'use_role')
        self.check_list_permission(Label, requested_use_labels)
        self.check_list_permission(InstanceGroup, requested_use_instance_groups)  # TODO: change to use_role for conflict
        self.check_list_permission(ExecutionEnvironment, requested_use_execution_environments)  # TODO: change if roles introduced

        jobs_object = self.get_objectified_jobs(attrs, key_to_obj_map)

        attrs['jobs'] = jobs_object
        if 'extra_vars' in attrs:
            extra_vars_dict = parse_yaml_or_json(attrs['extra_vars'])
            attrs['extra_vars'] = json.dumps(extra_vars_dict)
        attrs = super().validate(attrs)
        return attrs

    def check_list_permission(self, model, id_list, role_field=None):
        if not id_list:
            return
        user = self.context['request'].user
        if role_field is None:  # implies "read" level permission is required
            access_qs = user.get_queryset(model)
        else:
            access_qs = model.accessible_objects(user, role_field)

        not_allowed = set(id_list) - set(access_qs.filter(id__in=id_list).values_list('id', flat=True))
        if not_allowed:
            raise serializers.ValidationError(
                _("{model_name} {not_allowed} not found or you don't have permissions to access it").format(
                    model_name=model._meta.verbose_name_plural.title(), not_allowed=not_allowed
                )
            )

    def create(self, validated_data):
        request = self.context.get('request', None)
        launch_user = request.user if request else None
        job_node_data = validated_data.pop('jobs')
        wfj_deferred_attr_names = ('skip_tags', 'limit', 'job_tags')
        wfj_deferred_vals = {}
        for item in wfj_deferred_attr_names:
            wfj_deferred_vals[item] = validated_data.pop(item, None)

        wfj = WorkflowJob.objects.create(**validated_data, is_bulk_job=True, launch_type='manual', created_by=launch_user)
        for key, val in wfj_deferred_vals.items():
            if val:
                setattr(wfj, key, val)
        nodes = []
        node_m2m_objects = {}
        node_m2m_object_types_to_through_model = {
            'credentials': WorkflowJobNode.credentials.through,
            'labels': WorkflowJobNode.labels.through,
            'instance_groups': WorkflowJobNode.instance_groups.through,
        }
        node_deferred_attr_names = (
            'limit',
            'scm_branch',
            'verbosity',
            'forks',
            'diff_mode',
            'job_tags',
            'job_type',
            'skip_tags',
            'job_slice_count',
            'timeout',
        )
        node_deferred_attrs = {}
        for node_attrs in job_node_data:
            # we need to add any m2m objects after creation via the through model
            node_m2m_objects[node_attrs['identifier']] = {}
            node_deferred_attrs[node_attrs['identifier']] = {}
            for item in node_m2m_object_types_to_through_model.keys():
                if item in node_attrs:
                    node_m2m_objects[node_attrs['identifier']][item] = node_attrs.pop(item)

            # Some attributes are not accepted by WorkflowJobNode __init__, we have to set them after
            for item in node_deferred_attr_names:
                if item in node_attrs:
                    node_deferred_attrs[node_attrs['identifier']][item] = node_attrs.pop(item)

            # Create the node objects
            node_obj = WorkflowJobNode(workflow_job=wfj, created=wfj.created, modified=wfj.modified, **node_attrs)

            # we can set the deferred attrs now
            for item, value in node_deferred_attrs[node_attrs['identifier']].items():
                setattr(node_obj, item, value)

            # the node is now ready to be bulk created
            nodes.append(node_obj)

            # we'll need this later when we do the m2m through model bulk create
            node_m2m_objects[node_attrs['identifier']]['node'] = node_obj

        WorkflowJobNode.objects.bulk_create(nodes)

        # Deal with the m2m objects we have to create once the node exists
        for field_name, through_model in node_m2m_object_types_to_through_model.items():
            through_model_objects = []
            for node_identifier in node_m2m_objects.keys():
                if field_name in node_m2m_objects[node_identifier] and field_name == 'credentials':
                    for cred in node_m2m_objects[node_identifier][field_name]:
                        through_model_objects.append(through_model(credential=cred, workflowjobnode=node_m2m_objects[node_identifier]['node']))
                if field_name in node_m2m_objects[node_identifier] and field_name == 'labels':
                    for label in node_m2m_objects[node_identifier][field_name]:
                        through_model_objects.append(through_model(label=label, workflowjobnode=node_m2m_objects[node_identifier]['node']))
                if field_name in node_m2m_objects[node_identifier] and field_name == 'instance_groups':
                    for instance_group in node_m2m_objects[node_identifier][field_name]:
                        through_model_objects.append(through_model(instancegroup=instance_group, workflowjobnode=node_m2m_objects[node_identifier]['node']))
            if through_model_objects:
                through_model.objects.bulk_create(through_model_objects)

        wfj.save()
        wfj.signal_start()

        return WorkflowJobSerializer().to_representation(wfj)

    def check_organization_permission(self, attrs, request):
        # validate Organization
        # - If the orgs is not set, set it to the org of the launching user
        # - If the user is part of multiple orgs, throw a validation error saying user is part of multiple orgs, please provide one
        if not request.user.is_superuser:
            read_org_qs = Organization.accessible_objects(request.user, 'member_role')
            if 'organization' not in attrs or attrs['organization'] == None or attrs['organization'] == '':
                read_org_ct = read_org_qs.count()
                if read_org_ct == 1:
                    attrs['organization'] = read_org_qs.first()
                elif read_org_ct > 1:
                    raise serializers.ValidationError("User has permission to multiple Organizations, please set one of them in the request")
                else:
                    raise serializers.ValidationError("User not part of any organization, please assign an organization to assign to the bulk job")
            else:
                allowed_orgs = set(read_org_qs.values_list('id', flat=True))
                requested_org = attrs['organization']
                if requested_org.id not in allowed_orgs:
                    raise ValidationError(_(f"Organization {requested_org.id} not found or you don't have permissions to access it"))

    def get_objectified_jobs(self, attrs, key_to_obj_map):
        objectified_jobs = []
        # This loop is generalized so we should only have to add related items to the key_to_obj_map
        for job in attrs['jobs']:
            objectified_job = {}
            for key, value in job.items():
                if key in key_to_obj_map:
                    if isinstance(value, int):
                        objectified_job[key] = key_to_obj_map[key][value]
                    elif isinstance(value, list):
                        objectified_job[key] = [key_to_obj_map[key][item] for item in value]
                else:
                    objectified_job[key] = value
            objectified_jobs.append(objectified_job)
        return objectified_jobs
