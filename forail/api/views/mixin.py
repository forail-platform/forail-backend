# Copyright (c) 2018 Red Hat, Inc.
# All Rights Reserved.

import dateutil
import functools
import logging
import re

from django.conf import settings
from django.core.exceptions import FieldError
from django.db.models import Count
from django.db import IntegrityError, ProgrammingError, transaction, connection
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import APIException, PermissionDenied, ParseError, NotFound
from rest_framework.response import Response
from rest_framework.views import exception_handler
from rest_framework import status

from ansible_base.resource_registry.shared_types import OrganizationType, TeamType, UserType

from forail.main.constants import ACTIVE_STATES
from forail.main.utils import get_object_or_400
from forail.main.models.ha import Instance, InstanceGroup, schedule_policy_task
from forail.main.models.organization import Team
from forail.main.models.projects import Project
from forail.main.models.inventory import Inventory
from forail.main.models.jobs import JobTemplate
from forail.main import models
from forail.api.exceptions import ActiveJobConflict
from forail.api import renderers

logger = logging.getLogger('forail.api.views.mixin')


class UnifiedJobDeletionMixin(object):
    """
    Special handling when deleting a running unified job object.
    """

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if not request.user.can_access(self.model, 'delete', obj):
            raise PermissionDenied()
        try:
            if obj.unified_job_node.workflow_job.status in ACTIVE_STATES:
                raise PermissionDenied(detail=_('Cannot delete job resource when associated workflow job is running.'))
        except self.model.unified_job_node.RelatedObjectDoesNotExist:
            pass
        # Still allow deletion of new status, because these can be manually created
        if obj.status in ACTIVE_STATES and obj.status != 'new':
            raise PermissionDenied(detail=_("Cannot delete running job resource."))
        elif not obj.event_processing_finished:
            # Prohibit deletion if job events are still coming in
            if obj.finished and now() < obj.finished + dateutil.relativedelta.relativedelta(minutes=1):
                # less than 1 minute has passed since job finished and events are not in
                return Response({"error": _("Job has not finished processing events.")}, status=status.HTTP_400_BAD_REQUEST)
            else:
                # if it has been > 1 minute, events are probably lost
                logger.warning('Allowing deletion of {} through the API without all events processed.'.format(obj.log_format))

        # Manually cascade delete events if unpartitioned job
        if obj.has_unpartitioned_events:
            obj.get_event_queryset().delete()

        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InstanceGroupMembershipMixin(object):
    """
    This mixin overloads attach/detach so that it calls InstanceGroup.save(),
    triggering a background recalculation of policy-based instance group
    membership.
    """

    def attach(self, request, *args, **kwargs):
        response = super(InstanceGroupMembershipMixin, self).attach(request, *args, **kwargs)
        if status.is_success(response.status_code):
            sub_id = request.data.get('id', None)
            if self.parent_model is Instance:
                inst_name = self.get_parent_object().hostname
            else:
                inst_name = get_object_or_400(self.model, pk=sub_id).hostname
            with transaction.atomic():
                instance_groups_queryset = InstanceGroup.objects.select_for_update()
                if self.parent_model is Instance:
                    ig_obj = get_object_or_400(instance_groups_queryset, pk=sub_id)
                else:
                    # similar to get_parent_object, but selected for update
                    parent_filter = {self.lookup_field: self.kwargs.get(self.lookup_field, None)}
                    ig_obj = get_object_or_404(instance_groups_queryset, **parent_filter)
                if inst_name not in ig_obj.policy_instance_list:
                    ig_obj.policy_instance_list.append(inst_name)
                    ig_obj.save(update_fields=['policy_instance_list'])
        return response

    def unattach(self, request, *args, **kwargs):
        response = super(InstanceGroupMembershipMixin, self).unattach(request, *args, **kwargs)
        if status.is_success(response.status_code):
            sub_id = request.data.get('id', None)
            if self.parent_model is Instance:
                inst_name = self.get_parent_object().hostname
            else:
                inst_name = get_object_or_400(self.model, pk=sub_id).hostname
            with transaction.atomic():
                instance_groups_queryset = InstanceGroup.objects.select_for_update()
                if self.parent_model is Instance:
                    ig_obj = get_object_or_400(instance_groups_queryset, pk=sub_id)
                else:
                    # similar to get_parent_object, but selected for update
                    parent_filter = {self.lookup_field: self.kwargs.get(self.lookup_field, None)}
                    ig_obj = get_object_or_404(instance_groups_queryset, **parent_filter)
                if inst_name in ig_obj.policy_instance_list:
                    ig_obj.policy_instance_list.pop(ig_obj.policy_instance_list.index(inst_name))
                    ig_obj.save(update_fields=['policy_instance_list'])

            # sometimes removing an instance has a non-obvious consequence
            # this is almost always true if policy_instance_percentage or _minimum is non-zero
            # after removing a single instance, the other memberships need to be re-balanced
            schedule_policy_task()
        return response


class RelatedJobsPreventDeleteMixin(object):
    def perform_destroy(self, obj):
        self.check_related_active_jobs(obj)
        return super(RelatedJobsPreventDeleteMixin, self).perform_destroy(obj)

    def check_related_active_jobs(self, obj):
        active_jobs = obj.get_active_jobs()
        if len(active_jobs) > 0:
            raise ActiveJobConflict(active_jobs)
        time_cutoff = now() - dateutil.relativedelta.relativedelta(minutes=1)
        recent_jobs = obj._get_related_jobs().filter(finished__gte=time_cutoff)
        for unified_job in recent_jobs.get_real_instances():
            if not unified_job.event_processing_finished:
                raise PermissionDenied(_('Related job {} is still processing events.').format(unified_job.log_format))


class OrganizationCountsMixin(object):
    def get_serializer_context(self, *args, **kwargs):
        full_context = super(OrganizationCountsMixin, self).get_serializer_context(*args, **kwargs)

        if self.request is None:
            return full_context

        db_results = {}
        org_qs = self.model.accessible_objects(self.request.user, 'read_role')
        org_id_list = org_qs.values('id')
        if len(org_id_list) == 0:
            if self.request.method == 'POST':
                full_context['related_field_counts'] = {}
            return full_context

        inv_qs = Inventory.accessible_objects(self.request.user, 'read_role')
        project_qs = Project.accessible_objects(self.request.user, 'read_role')
        jt_qs = JobTemplate.accessible_objects(self.request.user, 'read_role')

        # Produce counts of Foreign Key relationships
        db_results['inventories'] = inv_qs.values('organization').annotate(Count('organization')).order_by('organization')

        db_results['teams'] = (
            Team.accessible_objects(self.request.user, 'read_role').values('organization').annotate(Count('organization')).order_by('organization')
        )

        db_results['job_templates'] = jt_qs.values('organization').annotate(Count('organization')).order_by('organization')

        db_results['projects'] = project_qs.values('organization').annotate(Count('organization')).order_by('organization')

        # Other members and admins of organization are always viewable
        db_results['users'] = org_qs.annotate(users=Count('member_role__members', distinct=True), admins=Count('admin_role__members', distinct=True)).values(
            'id', 'users', 'admins'
        )

        count_context = {}
        for org in org_id_list:
            org_id = org['id']
            count_context[org_id] = {'inventories': 0, 'teams': 0, 'users': 0, 'job_templates': 0, 'admins': 0, 'projects': 0}

        for res, count_qs in db_results.items():
            if res == 'users':
                org_reference = 'id'
            else:
                org_reference = 'organization'
            for entry in count_qs:
                org_id = entry[org_reference]
                if org_id in count_context:
                    if res == 'users':
                        count_context[org_id]['admins'] = entry['admins']
                        count_context[org_id]['users'] = entry['users']
                        continue
                    count_context[org_id][res] = entry['%s__count' % org_reference]

        full_context['related_field_counts'] = count_context

        return full_context


class NoTruncateMixin(object):
    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.query_params.get('no_truncate'):
            context.update(no_truncate=True)
        return context


def unpartitioned_event_horizon(cls):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE table_name = '_unpartitioned_{cls._meta.db_table}';")
        if not cursor.fetchone():
            return 0
    with connection.cursor() as cursor:
        try:
            cursor.execute(f'SELECT MAX(id) FROM _unpartitioned_{cls._meta.db_table}')
            return cursor.fetchone()[0] or -1
        except ProgrammingError:
            return 0


def api_exception_handler(exc, context):
    """
    Override default API exception handler to catch IntegrityError exceptions.
    """
    from forail.api.views.unified import UnifiedJobStdout

    if isinstance(exc, IntegrityError):
        exc = ParseError(exc.args[0])
    if isinstance(exc, FieldError):
        exc = ParseError(exc.args[0])
    if isinstance(context['view'], UnifiedJobStdout):
        context['view'].renderer_classes = [renderers.BrowsableAPIRenderer, JSONRenderer]
    if isinstance(exc, APIException):
        req = context['request']._request
        if 'forail.named_url_rewritten' in req.environ and not str(getattr(exc, 'status_code', 0)).startswith('2'):
            # if the URL was rewritten, and it's not a 2xx level status code,
            # revert the request.path to its original value to avoid leaking
            # any context about the existence of resources
            req.path = req.environ['forail.named_url_rewritten']
            if exc.status_code == 403:
                exc = NotFound(detail=_('Not found.'))
    return exception_handler(exc, context)


# Need JSONRenderer import for api_exception_handler
from rest_framework.renderers import JSONRenderer  # noqa: E402


class BadGateway(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = ''
    default_code = 'bad_gateway'


class GatewayTimeout(APIException):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    default_detail = ''
    default_code = 'gateway_timeout'


class HostRelatedSearchMixin(object):
    @property
    def related_search_fields(self):
        # Edge-case handle: https://github.com/ansible/ansible-tower/issues/7712
        ret = super(HostRelatedSearchMixin, self).related_search_fields
        ret.append('ansible_facts')
        return ret


class EnforceParentRelationshipMixin(object):
    """
    Useful when you have a self-referring ManyToManyRelationship.
    * Tower uses a shallow (2-deep only) url pattern. For example:

    When an object hangs off of a parent object you would have the url of the
    form /api/v2/parent_model/34/child_model. If you then wanted a child of the
    child model you would NOT do /api/v2/parent_model/34/child_model/87/child_child_model
    Instead, you would access the child_child_model via /api/v2/child_child_model/87/
    and you would create child_child_model's off of /api/v2/child_model/87/child_child_model_set
    Now, when creating child_child_model related to child_model you still want to
    link child_child_model to parent_model. That's what this class is for
    """

    enforce_parent_relationship = ''

    def update_raw_data(self, data):
        data.pop(self.enforce_parent_relationship, None)
        return super(EnforceParentRelationshipMixin, self).update_raw_data(data)

    def create(self, request, *args, **kwargs):
        # Inject parent group inventory ID into new group data.
        data = request.data
        # HACK: Make request data mutable.
        if getattr(data, '_mutable', None) is False:
            data._mutable = True
        data[self.enforce_parent_relationship] = getattr(self.get_parent_object(), '%s_id' % self.enforce_parent_relationship)
        return super(EnforceParentRelationshipMixin, self).create(request, *args, **kwargs)


def immutablesharedfields(cls):
    '''
    Class decorator to prevent modifying shared resources when ALLOW_LOCAL_RESOURCE_MANAGEMENT setting is set to False.

    Works by overriding these view methods:
    - create
    - delete
    - perform_update
    create and delete are overridden to raise a PermissionDenied exception.
    perform_update is overridden to check if any shared fields are being modified,
    and raise a PermissionDenied exception if so.
    '''
    # create instead of perform_create because some of our views
    # override create instead of perform_create
    if hasattr(cls, 'create'):
        cls.original_create = cls.create

        @functools.wraps(cls.create)
        def create_wrapper(*args, **kwargs):
            if settings.ALLOW_LOCAL_RESOURCE_MANAGEMENT:
                return cls.original_create(*args, **kwargs)
            raise PermissionDenied({'detail': _('Creation of this resource is not allowed. Create this resource via the platform ingress.')})

        cls.create = create_wrapper

    if hasattr(cls, 'delete'):
        cls.original_delete = cls.delete

        @functools.wraps(cls.delete)
        def delete_wrapper(*args, **kwargs):
            if settings.ALLOW_LOCAL_RESOURCE_MANAGEMENT:
                return cls.original_delete(*args, **kwargs)
            raise PermissionDenied({'detail': _('Deletion of this resource is not allowed. Delete this resource via the platform ingress.')})

        cls.delete = delete_wrapper

    if hasattr(cls, 'perform_update'):
        cls.original_perform_update = cls.perform_update

        @functools.wraps(cls.perform_update)
        def update_wrapper(*args, **kwargs):
            if not settings.ALLOW_LOCAL_RESOURCE_MANAGEMENT:
                view, serializer = args
                instance = view.get_object()
                if instance:
                    if isinstance(instance, models.Organization):
                        shared_fields = OrganizationType._declared_fields.keys()
                    elif isinstance(instance, models.User):
                        shared_fields = UserType._declared_fields.keys()
                    elif isinstance(instance, models.Team):
                        shared_fields = TeamType._declared_fields.keys()
                    attrs = serializer.validated_data
                    for field in shared_fields:
                        if field in attrs and getattr(instance, field) != attrs[field]:
                            raise PermissionDenied({field: _(f"Cannot change shared field '{field}'. Alter this field via the platform ingress.")})
            return cls.original_perform_update(*args, **kwargs)

        cls.perform_update = update_wrapper

    return cls


def redact_ansi(line):
    # Remove ANSI escape sequences used to embed event data.
    line = re.sub(r'\x1b\[K(?:[A-Za-z0-9+/=]+\x1b\[\d+D)+\x1b\[K', '', line)
    # Remove ANSI color escape sequences.
    return re.sub(r'\x1b[^m]*m', '', line)


class StdoutFilter(object):
    def __init__(self, fileobj):
        self._functions = []
        self.fileobj = fileobj
        self.extra_data = ''
        if hasattr(fileobj, 'close'):
            self.close = fileobj.close

    def read(self, size=-1):
        data = self.extra_data
        while size > 0 and len(data) < size:
            line = self.fileobj.readline(size)
            if not line:
                break
            line = self.process_line(line)
            data += line
        if size > 0 and len(data) > size:
            self.extra_data = data[size:]
            data = data[:size]
        else:
            self.extra_data = ''
        return data

    def register(self, func):
        self._functions.append(func)

    def process_line(self, line):
        for func in self._functions:
            line = func(line)
        return line
