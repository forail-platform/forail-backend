# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

import functools
import logging

from collections import OrderedDict

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.db.models.fields.related import ManyToManyField, ForeignKey
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied, ParseError
from rest_framework.response import Response
from rest_framework import status

from forail.main.utils import getattrd
from forail.main.scheduler.dag_workflow import WorkflowDAG
from forail.api.generics import (
    CopyAPIView,
    GenericAPIView,
    GenericCancelView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveDestroyAPIView,
    RetrieveUpdateDestroyAPIView,
    ResourceAccessList,
    SubListAPIView,
    SubListAttachDetachAPIView,
    SubListCreateAPIView,
    SubListCreateAttachDetachAPIView,
)
from forail.api.views.labels import LabelSubListCreateAttachDetachView
from forail.api.views.mixin import EnforceParentRelationshipMixin, RelatedJobsPreventDeleteMixin, UnifiedJobDeletionMixin
from forail.api.views.schedules import LaunchConfigCredentialsBase
from forail.api.views.job_templates import JobTemplateSurveySpec, JobTemplateLabelList
from forail.main.utils import ScheduleWorkflowManager
from forail.api import serializers
from forail.main import models

logger = logging.getLogger('forail.api.views')


class WorkflowJobTemplateSurveySpec(JobTemplateSurveySpec):
    model = models.WorkflowJobTemplate


class WorkflowJobNodeList(ListAPIView):
    model = models.WorkflowJobNode
    serializer_class = serializers.WorkflowJobNodeListSerializer
    search_fields = ('unified_job_template__name', 'unified_job_template__description')


class WorkflowJobNodeDetail(RetrieveAPIView):
    model = models.WorkflowJobNode
    serializer_class = serializers.WorkflowJobNodeDetailSerializer


class WorkflowJobNodeCredentialsList(SubListAPIView):
    model = models.Credential
    serializer_class = serializers.CredentialSerializer
    parent_model = models.WorkflowJobNode
    relationship = 'credentials'


class WorkflowJobNodeLabelsList(SubListAPIView):
    model = models.Label
    serializer_class = serializers.LabelSerializer
    parent_model = models.WorkflowJobNode
    relationship = 'labels'


class WorkflowJobNodeInstanceGroupsList(SubListAttachDetachAPIView):
    model = models.InstanceGroup
    serializer_class = serializers.InstanceGroupSerializer
    parent_model = models.WorkflowJobNode
    relationship = 'instance_groups'


class WorkflowJobTemplateNodeList(ListCreateAPIView):
    model = models.WorkflowJobTemplateNode
    serializer_class = serializers.WorkflowJobTemplateNodeSerializer
    search_fields = ('unified_job_template__name', 'unified_job_template__description')


class WorkflowJobTemplateNodeDetail(RetrieveUpdateDestroyAPIView):
    model = models.WorkflowJobTemplateNode
    serializer_class = serializers.WorkflowJobTemplateNodeDetailSerializer


class WorkflowJobTemplateNodeSurveySpec(RetrieveAPIView):
    """Get or set the survey spec for a workflow node."""
    model = models.WorkflowJobTemplateNode

    def get(self, request, *args, **kwargs):
        node = self.get_object()
        if not node.survey_enabled or not node.survey_spec:
            return Response({})
        return Response(node.survey_spec)

    def post(self, request, *args, **kwargs):
        node = self.get_object()
        node.survey_spec = request.data
        node.survey_enabled = True
        node.save(update_fields=['survey_spec', 'survey_enabled'])
        return Response(node.survey_spec)

    def delete(self, request, *args, **kwargs):
        node = self.get_object()
        node.survey_spec = {}
        node.survey_enabled = False
        node.save(update_fields=['survey_spec', 'survey_enabled'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkflowJobTemplateNodeCredentialsList(LaunchConfigCredentialsBase):
    parent_model = models.WorkflowJobTemplateNode


class WorkflowJobTemplateNodeLabelsList(LabelSubListCreateAttachDetachView):
    parent_model = models.WorkflowJobTemplateNode


class WorkflowJobTemplateNodeInstanceGroupsList(SubListAttachDetachAPIView):
    model = models.InstanceGroup
    serializer_class = serializers.InstanceGroupSerializer
    parent_model = models.WorkflowJobTemplateNode
    relationship = 'instance_groups'


class WorkflowJobTemplateNodeChildrenBaseList(EnforceParentRelationshipMixin, SubListCreateAttachDetachAPIView):
    model = models.WorkflowJobTemplateNode
    serializer_class = serializers.WorkflowJobTemplateNodeSerializer
    always_allow_superuser = True
    parent_model = models.WorkflowJobTemplateNode
    relationship = ''
    enforce_parent_relationship = 'workflow_job_template'
    search_fields = ('unified_job_template__name', 'unified_job_template__description')
    filter_read_permission = False

    def is_valid_relation(self, parent, sub, created=False):
        if created:
            return None

        if parent.id == sub.id:
            return {"Error": _("Cycle detected.")}

        '''
        Look for parent->child connection in all relationships except the relationship that is
        attempting to be added; because it's ok to re-add the relationship
        '''
        relationships = ['success_nodes', 'failure_nodes', 'always_nodes']
        relationships.remove(self.relationship)
        qs = functools.reduce(lambda x, y: (x | y), (Q(**{'{}__in'.format(r): [sub.id]}) for r in relationships))

        if models.WorkflowJobTemplateNode.objects.filter(Q(pk=parent.id) & qs).exists():
            return {"Error": _("Relationship not allowed.")}

        parent_node_type_relationship = getattr(parent, self.relationship)
        parent_node_type_relationship.add(sub)

        graph = WorkflowDAG(parent.workflow_job_template)
        if graph.has_cycle():
            parent_node_type_relationship.remove(sub)
            return {"Error": _("Cycle detected.")}
        parent_node_type_relationship.remove(sub)
        return None


class WorkflowJobTemplateNodeCreateApproval(RetrieveAPIView):
    model = models.WorkflowJobTemplateNode
    serializer_class = serializers.WorkflowJobTemplateNodeCreateApprovalSerializer
    permission_classes = []

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        serializer = self.get_serializer(instance=obj, data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        approval_template = obj.create_approval_template(**serializer.validated_data)
        data = serializers.WorkflowApprovalTemplateSerializer(approval_template, context=self.get_serializer_context()).data
        return Response(data, status=status.HTTP_201_CREATED)

    def check_permissions(self, request):
        if not request.user.is_authenticated:
            raise PermissionDenied()
        obj = self.get_object().workflow_job_template
        if request.method == 'POST':
            if not request.user.can_access(models.WorkflowJobTemplate, 'change', obj, request.data):
                self.permission_denied(request)
        else:
            if not request.user.can_access(models.WorkflowJobTemplate, 'read', obj):
                self.permission_denied(request)


class WorkflowJobTemplateNodeSuccessNodesList(WorkflowJobTemplateNodeChildrenBaseList):
    relationship = 'success_nodes'


class WorkflowJobTemplateNodeFailureNodesList(WorkflowJobTemplateNodeChildrenBaseList):
    relationship = 'failure_nodes'


class WorkflowJobTemplateNodeAlwaysNodesList(WorkflowJobTemplateNodeChildrenBaseList):
    relationship = 'always_nodes'


class WorkflowJobNodeChildrenBaseList(SubListAPIView):
    model = models.WorkflowJobNode
    serializer_class = serializers.WorkflowJobNodeListSerializer
    parent_model = models.WorkflowJobNode
    relationship = ''
    search_fields = ('unified_job_template__name', 'unified_job_template__description')
    filter_read_permission = False


class WorkflowJobNodeSuccessNodesList(WorkflowJobNodeChildrenBaseList):
    relationship = 'success_nodes'


class WorkflowJobNodeFailureNodesList(WorkflowJobNodeChildrenBaseList):
    relationship = 'failure_nodes'


class WorkflowJobNodeAlwaysNodesList(WorkflowJobNodeChildrenBaseList):
    relationship = 'always_nodes'


class WorkflowJobTemplateList(ListCreateAPIView):
    model = models.WorkflowJobTemplate
    serializer_class = serializers.WorkflowJobTemplateSerializer
    always_allow_superuser = False

    def check_permissions(self, request):
        if request.method == 'POST':
            can_access, messages = request.user.can_access_with_errors(self.model, 'add', request.data)
            if not can_access:
                self.permission_denied(request, message=messages)

        super(WorkflowJobTemplateList, self).check_permissions(request)


class WorkflowJobTemplateDetail(RelatedJobsPreventDeleteMixin, RetrieveUpdateDestroyAPIView):
    model = models.WorkflowJobTemplate
    serializer_class = serializers.WorkflowJobTemplateSerializer
    always_allow_superuser = False


class WorkflowJobTemplateCopy(CopyAPIView):
    model = models.WorkflowJobTemplate
    copy_return_serializer_class = serializers.WorkflowJobTemplateSerializer

    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        if not request.user.can_access(obj.__class__, 'read', obj):
            raise PermissionDenied()
        can_copy, messages = request.user.can_access_with_errors(self.model, 'copy', obj)
        data = OrderedDict(
            [
                ('can_copy', can_copy),
                ('can_copy_without_user_input', can_copy),
                ('templates_unable_to_copy', [] if can_copy else ['all']),
                ('credentials_unable_to_copy', [] if can_copy else ['all']),
                ('inventories_unable_to_copy', [] if can_copy else ['all']),
            ]
        )
        if messages and can_copy:
            data['can_copy_without_user_input'] = False
            data.update(messages)
        return Response(data)

    def _build_create_dict(self, obj):
        """Special processing of fields managed by char_prompts"""
        r = super(WorkflowJobTemplateCopy, self)._build_create_dict(obj)
        field_names = set(f.name for f in obj._meta.get_fields())
        for field_name, ask_field_name in obj.get_ask_mapping().items():
            if field_name in r and field_name not in field_names:
                r.setdefault('char_prompts', {})
                r['char_prompts'][field_name] = r.pop(field_name)
        return r

    @staticmethod
    def deep_copy_permission_check_func(user, new_objs):
        for obj in new_objs:
            for field_name in obj._get_workflow_job_field_names():
                item = getattr(obj, field_name, None)
                if item is None:
                    continue
                elif field_name in ['inventory']:
                    if not user.can_access(item.__class__, 'use', item):
                        setattr(obj, field_name, None)
                elif field_name in ['unified_job_template']:
                    if not user.can_access(item.__class__, 'start', item, validate_license=False):
                        setattr(obj, field_name, None)
                elif field_name in ['credentials']:
                    for cred in item.all():
                        if not user.can_access(cred.__class__, 'use', cred):
                            logger.debug('Deep copy: removing {} from relationship due to permissions'.format(cred))
                            item.remove(cred.pk)
            obj.save()


class WorkflowJobTemplateLabelList(JobTemplateLabelList):
    parent_model = models.WorkflowJobTemplate


class WorkflowJobTemplateLaunch(RetrieveAPIView):
    model = models.WorkflowJobTemplate
    obj_permission_type = 'start'
    serializer_class = serializers.WorkflowJobLaunchSerializer
    always_allow_superuser = False

    def update_raw_data(self, data):
        try:
            obj = self.get_object()
        except PermissionDenied:
            return data
        extra_vars = data.pop('extra_vars', None) or {}
        if obj:
            for v in obj.variables_needed_to_start:
                extra_vars.setdefault(v, u'')
            if extra_vars:
                data['extra_vars'] = extra_vars
            modified_ask_mapping = models.WorkflowJobTemplate.get_ask_mapping()
            modified_ask_mapping.pop('extra_vars')

            for field, ask_field_name in modified_ask_mapping.items():
                if not getattr(obj, ask_field_name):
                    data.pop(field, None)
                elif isinstance(getattr(obj.__class__, field).field, ForeignKey):
                    data[field] = getattrd(obj, "%s.%s" % (field, 'id'), None)
                elif isinstance(getattr(obj.__class__, field).field, ManyToManyField):
                    data[field] = [item.id for item in getattr(obj, field).all()]
                else:
                    data[field] = getattr(obj, field)

        return data

    def post(self, request, *args, **kwargs):
        obj = self.get_object()

        if 'inventory_id' in request.data:
            request.data['inventory'] = request.data['inventory_id']

        serializer = self.serializer_class(instance=obj, data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if not request.user.can_access(models.JobLaunchConfig, 'add', serializer.validated_data, template=obj):
            raise PermissionDenied()

        new_job = obj.create_unified_job(**serializer.validated_data)

        from forail.main.observability.tracing import span
        from forail.main.observability import metrics as _otel_metrics

        with span(
            'forail.launch',
            template_id=getattr(obj, 'id', None),
            template_type='workflow_job_template',
            user_id=getattr(request.user, 'id', None),
            organization_id=getattr(getattr(obj, 'organization', None), 'id', None),
        ) as launch_span:
            # Tenant quota gate (no-op when TENANCY_ENABLED is False)
            from forail.main.tenancy.quota import check_tenant_quota
            quota_result = check_tenant_quota(new_job, request)
            if not quota_result.allowed:
                launch_span.set_attribute('result', 'blocked')
                launch_span.set_attribute('gate_blocked', 'tenant_quota')
                new_job.delete()
                return Response(
                    {'detail': 'Tenant quota exceeded.', 'reasons': quota_result.reasons},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            # Policy-as-Code gate (no-op when OPA is disabled)
            from forail.main.policy.evaluator import evaluate_launch
            policy_result = evaluate_launch(new_job, request)
            if not policy_result.allowed:
                launch_span.set_attribute('result', 'blocked')
                launch_span.set_attribute('gate_blocked', 'policy')
                _otel_metrics.inc_jobs_blocked('policy')
                new_job.delete()
                return Response(
                    {'detail': 'Policy denied launch.', 'reasons': policy_result.deny_messages},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if policy_result.warn_messages:
                existing = new_job.job_explanation or ''
                new_job.job_explanation = (existing + '\nPolicy warnings: ' +
                                            '; '.join(policy_result.warn_messages))[:1024]
                new_job.save(update_fields=['job_explanation'])

            # IaC Scanning gate (no-op when SCANNER_ENABLED is False)
            from forail.main.scanning.runner import run_scanners_for_launch
            scan_result = run_scanners_for_launch(new_job, request)
            if not scan_result.allowed:
                launch_span.set_attribute('result', 'blocked')
                launch_span.set_attribute('gate_blocked', 'scanner')
                _otel_metrics.inc_jobs_blocked('scanner')
                new_job.delete()
                return Response(
                    {'detail': 'Scanner blocked launch.', 'reasons': scan_result.block_messages},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if scan_result.warn_messages:
                existing = new_job.job_explanation or ''
                new_job.job_explanation = (existing + '\nScan warnings: ' +
                                            '; '.join(scan_result.warn_messages))[:1024]
                new_job.save(update_fields=['job_explanation'])

            launch_span.set_attribute('result', 'allowed')
            _otel_metrics.inc_jobs_launched('workflow_job_template', 'launched')
            new_job.signal_start()

        data = OrderedDict()
        data['workflow_job'] = new_job.id
        data['ignored_fields'] = serializer._ignored_fields
        data.update(serializers.WorkflowJobSerializer(new_job, context=self.get_serializer_context()).to_representation(new_job))
        headers = {'Location': new_job.get_absolute_url(request)}
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)


class WorkflowJobRelaunch(GenericAPIView):
    model = models.WorkflowJob
    obj_permission_type = 'start'
    serializer_class = serializers.EmptySerializer

    def check_object_permissions(self, request, obj):
        if request.method == 'POST' and obj:
            relaunch_perm, messages = request.user.can_access_with_errors(self.model, 'start', obj)
            if not relaunch_perm and 'workflow_job_template' in messages:
                self.permission_denied(request, message=messages['workflow_job_template'])
        return super(WorkflowJobRelaunch, self).check_object_permissions(request, obj)

    def get(self, request, *args, **kwargs):
        return Response({})

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.is_sliced_job:
            jt = obj.job_template
            if not jt:
                raise ParseError(_('Cannot relaunch slice workflow job orphaned from job template.'))
            elif not obj.inventory or min(obj.inventory.hosts.count(), jt.job_slice_count) != obj.workflow_nodes.count():
                raise ParseError(_('Cannot relaunch sliced workflow job after slice count has changed.'))
        new_workflow_job = obj.create_relaunch_workflow_job()
        new_workflow_job.signal_start()

        data = serializers.WorkflowJobSerializer(new_workflow_job, context=self.get_serializer_context()).data
        headers = {'Location': new_workflow_job.get_absolute_url(request=request)}
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)


class WorkflowJobTemplateWorkflowNodesList(SubListCreateAPIView):
    model = models.WorkflowJobTemplateNode
    serializer_class = serializers.WorkflowJobTemplateNodeSerializer
    parent_model = models.WorkflowJobTemplate
    relationship = 'workflow_job_template_nodes'
    parent_key = 'workflow_job_template'
    search_fields = ('unified_job_template__name', 'unified_job_template__description')
    ordering = ('id',)  # assure ordering by id for consistency
    filter_read_permission = False


class WorkflowJobTemplateJobsList(SubListAPIView):
    model = models.WorkflowJob
    serializer_class = serializers.WorkflowJobListSerializer
    parent_model = models.WorkflowJobTemplate
    relationship = 'workflow_jobs'
    parent_key = 'workflow_job_template'


class WorkflowJobTemplateSchedulesList(SubListCreateAPIView):
    name = _("Workflow Job Template Schedules")

    model = models.Schedule
    serializer_class = serializers.ScheduleSerializer
    parent_model = models.WorkflowJobTemplate
    relationship = 'schedules'
    parent_key = 'unified_job_template'


class WorkflowJobTemplateNotificationTemplatesAnyList(SubListCreateAttachDetachAPIView):
    model = models.NotificationTemplate
    serializer_class = serializers.NotificationTemplateSerializer
    parent_model = models.WorkflowJobTemplate


class WorkflowJobTemplateNotificationTemplatesStartedList(WorkflowJobTemplateNotificationTemplatesAnyList):
    relationship = 'notification_templates_started'


class WorkflowJobTemplateNotificationTemplatesErrorList(WorkflowJobTemplateNotificationTemplatesAnyList):
    relationship = 'notification_templates_error'


class WorkflowJobTemplateNotificationTemplatesSuccessList(WorkflowJobTemplateNotificationTemplatesAnyList):
    relationship = 'notification_templates_success'


class WorkflowJobTemplateNotificationTemplatesApprovalList(WorkflowJobTemplateNotificationTemplatesAnyList):
    relationship = 'notification_templates_approvals'


class WorkflowJobTemplateAccessList(ResourceAccessList):
    model = models.User  # needs to be User for AccessLists's
    parent_model = models.WorkflowJobTemplate


class WorkflowJobTemplateObjectRolesList(SubListAPIView):
    deprecated = True
    model = models.Role
    serializer_class = serializers.RoleSerializer
    parent_model = models.WorkflowJobTemplate
    search_fields = ('role_field', 'content_type__model')
    deprecated = True

    def get_queryset(self):
        po = self.get_parent_object()
        content_type = ContentType.objects.get_for_model(self.parent_model)
        return models.Role.objects.filter(content_type=content_type, object_id=po.pk)


class WorkflowJobTemplateActivityStreamList(SubListAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
    parent_model = models.WorkflowJobTemplate
    relationship = 'activitystream_set'
    search_fields = ('changes',)

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)
        qs = self.request.user.get_queryset(self.model)
        return qs.filter(Q(workflow_job_template=parent) | Q(workflow_job_template_node__workflow_job_template=parent)).distinct()


class WorkflowJobList(ListAPIView):
    model = models.WorkflowJob
    serializer_class = serializers.WorkflowJobListSerializer


class WorkflowJobDetail(UnifiedJobDeletionMixin, RetrieveDestroyAPIView):
    model = models.WorkflowJob
    serializer_class = serializers.WorkflowJobSerializer


class WorkflowJobWorkflowNodesList(SubListAPIView):
    model = models.WorkflowJobNode
    serializer_class = serializers.WorkflowJobNodeListSerializer
    always_allow_superuser = True
    parent_model = models.WorkflowJob
    relationship = 'workflow_job_nodes'
    parent_key = 'workflow_job'
    search_fields = ('unified_job_template__name', 'unified_job_template__description')
    ordering = ('id',)  # assure ordering by id for consistency
    filter_read_permission = False


class WorkflowJobCancel(GenericCancelView):
    model = models.WorkflowJob
    serializer_class = serializers.WorkflowJobCancelSerializer

    def post(self, request, *args, **kwargs):
        r = super().post(request, *args, **kwargs)
        ScheduleWorkflowManager().schedule()
        return r


class WorkflowJobNotificationsList(SubListAPIView):
    model = models.Notification
    serializer_class = serializers.NotificationSerializer
    parent_model = models.WorkflowJob
    relationship = 'notifications'
    search_fields = ('subject', 'notification_type', 'body')

    def get_sublist_queryset(self, parent):
        return self.model.objects.filter(
            Q(unifiedjob_notifications=parent)
            | Q(unifiedjob_notifications__unified_job_node__workflow_job=parent, unifiedjob_notifications__workflowapproval__isnull=False)
        ).distinct()


class WorkflowJobActivityStreamList(SubListAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
    parent_model = models.WorkflowJob
    relationship = 'activitystream_set'
    search_fields = ('changes',)


class WorkflowJobLabelList(SubListAPIView):
    model = models.Label
    serializer_class = serializers.LabelSerializer
    parent_model = models.WorkflowJob
    relationship = 'labels'
