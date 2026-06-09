# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from collections import OrderedDict

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework import status

from rest_framework_yaml.parsers import YAMLParser
from rest_framework_yaml.renderers import YAMLRenderer

from forail.main.tasks.system import update_inventory_computed_fields
from forail.main.utils import ignore_inventory_computed_fields
from forail.api.generics import (
    GenericCancelView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateAPIView,
    RetrieveUpdateDestroyAPIView,
    RetrieveDestroyAPIView,
    SubListAPIView,
    SubListCreateAPIView,
    SubListAttachDetachAPIView,
    SubListCreateAttachDetachAPIView,
    SubListDestroyAPIView,
)
from forail.api.views.mixin import HostRelatedSearchMixin, RelatedJobsPreventDeleteMixin, UnifiedJobDeletionMixin
from forail.api.views.unified import UnifiedJobStdout
from forail.api.permissions import TaskPermission, InventoryInventorySourcesUpdatePermission, VariableDataPermission
from forail.api import serializers
from forail.main import models


class InventoryGroupsList(SubListCreateAttachDetachAPIView):
    model = models.Group
    serializer_class = serializers.GroupSerializer
    parent_model = models.Inventory
    relationship = 'groups'
    parent_key = 'inventory'


class InventoryRootGroupsList(SubListCreateAttachDetachAPIView):
    model = models.Group
    serializer_class = serializers.GroupSerializer
    parent_model = models.Inventory
    relationship = 'groups'
    parent_key = 'inventory'

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)
        qs = self.request.user.get_queryset(self.model).distinct()  # need distinct for '&' operator
        return qs & parent.root_groups


class BaseVariableData(RetrieveUpdateAPIView):
    parser_classes = api_settings.DEFAULT_PARSER_CLASSES + [YAMLParser]
    renderer_classes = api_settings.DEFAULT_RENDERER_CLASSES + [YAMLRenderer]
    permission_classes = (VariableDataPermission,)


class InventoryVariableData(BaseVariableData):
    model = models.Inventory
    serializer_class = serializers.InventoryVariableDataSerializer


class HostVariableData(BaseVariableData):
    model = models.Host
    serializer_class = serializers.HostVariableDataSerializer


class GroupVariableData(BaseVariableData):
    model = models.Group
    serializer_class = serializers.GroupVariableDataSerializer


class InventoryScriptView(RetrieveAPIView):
    model = models.Inventory
    serializer_class = serializers.InventoryScriptSerializer
    permission_classes = (TaskPermission,)
    filter_backends = ()

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        hostname = request.query_params.get('host', '')
        hostvars = bool(request.query_params.get('hostvars', ''))
        towervars = bool(request.query_params.get('towervars', ''))
        show_all = bool(request.query_params.get('all', ''))
        subset = request.query_params.get('subset', '')
        if subset:
            if not isinstance(subset, str):
                raise ParseError(_('Inventory subset argument must be a string.'))
            if subset.startswith('slice'):
                slice_number, slice_count = models.Inventory.parse_slice_params(subset)
            else:
                raise ParseError(_('Subset does not use any supported syntax.'))
        else:
            slice_number, slice_count = 1, 1
        if hostname:
            hosts_q = dict(name=hostname)
            if not show_all:
                hosts_q['enabled'] = True
            host = get_object_or_404(obj.hosts, **hosts_q)
            return Response(host.variables_dict)
        return Response(obj.get_script_data(hostvars=hostvars, towervars=towervars, show_all=show_all, slice_number=slice_number, slice_count=slice_count))


class InventoryTreeView(RetrieveAPIView):
    model = models.Inventory
    serializer_class = serializers.GroupTreeSerializer
    filter_backends = ()

    def _populate_group_children(self, group_data, all_group_data_map, group_children_map):
        if 'children' in group_data:
            return
        group_data['children'] = []
        for child_id in group_children_map.get(group_data['id'], set()):
            group_data['children'].append(all_group_data_map[child_id])
        group_data['children'].sort(key=lambda x: x['name'])
        for child_data in group_data['children']:
            self._populate_group_children(child_data, all_group_data_map, group_children_map)

    def retrieve(self, request, *args, **kwargs):
        inventory = self.get_object()
        group_children_map = inventory.get_group_children_map()
        root_group_pks = inventory.root_groups.order_by('name').values_list('pk', flat=True)
        groups_qs = inventory.groups
        groups_qs = groups_qs.prefetch_related('inventory_sources')
        all_group_data = serializers.GroupSerializer(groups_qs, many=True).data
        all_group_data_map = dict((x['id'], x) for x in all_group_data)
        tree_data = [all_group_data_map[x] for x in root_group_pks]
        for group_data in tree_data:
            self._populate_group_children(group_data, all_group_data_map, group_children_map)
        return Response(tree_data)


class InventoryInventorySourcesList(SubListCreateAPIView):
    name = _('Inventory Source List')

    model = models.InventorySource
    serializer_class = serializers.InventorySourceSerializer
    parent_model = models.Inventory
    # Sometimes creation blocked by SCM inventory source restrictions
    always_allow_superuser = False
    relationship = 'inventory_sources'
    parent_key = 'inventory'


class InventoryInventorySourcesUpdate(RetrieveAPIView):
    name = _('Inventory Sources Update')

    model = models.Inventory
    obj_permission_type = 'start'
    serializer_class = serializers.InventorySourceUpdateSerializer
    permission_classes = (InventoryInventorySourcesUpdatePermission,)

    def retrieve(self, request, *args, **kwargs):
        inventory = self.get_object()
        update_data = []
        for inventory_source in inventory.inventory_sources.exclude(source=''):
            details = {'inventory_source': inventory_source.pk, 'can_update': inventory_source.can_update}
            update_data.append(details)
        return Response(update_data)

    def post(self, request, *args, **kwargs):
        inventory = self.get_object()
        update_data = []
        successes = 0
        failures = 0
        for inventory_source in inventory.inventory_sources.exclude(source=''):
            details = OrderedDict()
            details['inventory_source'] = inventory_source.pk
            details['status'] = None
            if inventory_source.can_update:
                update = inventory_source.update()
                details.update(serializers.InventoryUpdateDetailSerializer(update, context=self.get_serializer_context()).to_representation(update))
                details['status'] = 'started'
                details['inventory_update'] = update.id
                successes += 1
            else:
                if not details.get('status'):
                    details['status'] = _('Could not start because `can_update` returned False')
                failures += 1
            update_data.append(details)
        if failures and successes:
            status_code = status.HTTP_202_ACCEPTED
        elif failures and not successes:
            status_code = status.HTTP_400_BAD_REQUEST
        elif not failures and not successes:
            return Response({'detail': _('No inventory sources to update.')}, status=status.HTTP_400_BAD_REQUEST)
        else:
            status_code = status.HTTP_200_OK
        return Response(update_data, status=status_code)


class InventorySourceList(ListCreateAPIView):
    model = models.InventorySource
    serializer_class = serializers.InventorySourceSerializer
    always_allow_superuser = False


class InventorySourceDetail(RelatedJobsPreventDeleteMixin, RetrieveUpdateDestroyAPIView):
    model = models.InventorySource
    serializer_class = serializers.InventorySourceSerializer


class InventorySourceSchedulesList(SubListCreateAPIView):
    name = _("Inventory Source Schedules")

    model = models.Schedule
    serializer_class = serializers.ScheduleSerializer
    parent_model = models.InventorySource
    relationship = 'schedules'
    parent_key = 'unified_job_template'


class InventorySourceActivityStreamList(SubListAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
    parent_model = models.InventorySource
    relationship = 'activitystream_set'
    search_fields = ('changes',)


class InventorySourceNotificationTemplatesAnyList(SubListCreateAttachDetachAPIView):
    model = models.NotificationTemplate
    serializer_class = serializers.NotificationTemplateSerializer
    parent_model = models.InventorySource

    def post(self, request, *args, **kwargs):
        parent = self.get_parent_object()
        if parent.source not in models.CLOUD_INVENTORY_SOURCES:
            return Response(
                dict(msg=_("Notification Templates can only be assigned when source is one of {}.").format(models.CLOUD_INVENTORY_SOURCES, parent.source)),
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super(InventorySourceNotificationTemplatesAnyList, self).post(request, *args, **kwargs)


class InventorySourceNotificationTemplatesStartedList(InventorySourceNotificationTemplatesAnyList):
    relationship = 'notification_templates_started'


class InventorySourceNotificationTemplatesErrorList(InventorySourceNotificationTemplatesAnyList):
    relationship = 'notification_templates_error'


class InventorySourceNotificationTemplatesSuccessList(InventorySourceNotificationTemplatesAnyList):
    relationship = 'notification_templates_success'


class InventorySourceHostsList(HostRelatedSearchMixin, SubListDestroyAPIView):
    model = models.Host
    serializer_class = serializers.HostSerializer
    parent_model = models.InventorySource
    relationship = 'hosts'
    check_sub_obj_permission = False

    def perform_list_destroy(self, instance_list):
        inv_source = self.get_parent_object()
        with ignore_inventory_computed_fields():
            if not settings.ACTIVITY_STREAM_ENABLED_FOR_INVENTORY_SYNC:
                from forail.main.signals import disable_activity_stream

                with disable_activity_stream():
                    # job host summary deletion necessary to avoid deadlock
                    models.JobHostSummary.objects.filter(host__inventory_sources=inv_source).update(host=None)
                    models.Host.objects.filter(inventory_sources=inv_source).delete()
                    r = super(InventorySourceHostsList, self).perform_list_destroy([])
            else:
                # Advance delete of group-host memberships to prevent deadlock
                # Activity stream doesn't record disassociation here anyway
                # no signals-related reason to not bulk-delete
                models.Host.groups.through.objects.filter(host__inventory_sources=inv_source).delete()
                r = super(InventorySourceHostsList, self).perform_list_destroy(instance_list)
        update_inventory_computed_fields.delay(inv_source.inventory_id)
        return r


class InventorySourceGroupsList(SubListDestroyAPIView):
    model = models.Group
    serializer_class = serializers.GroupSerializer
    parent_model = models.InventorySource
    relationship = 'groups'
    check_sub_obj_permission = False

    def perform_list_destroy(self, instance_list):
        inv_source = self.get_parent_object()
        with ignore_inventory_computed_fields():
            if not settings.ACTIVITY_STREAM_ENABLED_FOR_INVENTORY_SYNC:
                from forail.main.signals import disable_activity_stream

                with disable_activity_stream():
                    models.Group.objects.filter(inventory_sources=inv_source).delete()
                    r = super(InventorySourceGroupsList, self).perform_list_destroy([])
            else:
                # Advance delete of group-host memberships to prevent deadlock
                # Same arguments for bulk delete as with host list
                models.Group.hosts.through.objects.filter(group__inventory_sources=inv_source).delete()
                r = super(InventorySourceGroupsList, self).perform_list_destroy(instance_list)
        update_inventory_computed_fields.delay(inv_source.inventory_id)
        return r


class InventorySourceUpdatesList(SubListAPIView):
    model = models.InventoryUpdate
    serializer_class = serializers.InventoryUpdateListSerializer
    parent_model = models.InventorySource
    relationship = 'inventory_updates'


class InventorySourceCredentialsList(SubListAttachDetachAPIView):
    parent_model = models.InventorySource
    model = models.Credential
    serializer_class = serializers.CredentialSerializer
    relationship = 'credentials'

    def is_valid_relation(self, parent, sub, created=False):
        # Inventory source credentials are exclusive with all other credentials
        # subject to change for https://github.com/ansible/awx/issues/277
        # or https://github.com/ansible/awx/issues/223
        if parent.credentials.exists():
            return {'msg': _("Source already has credential assigned.")}
        error = models.InventorySource.cloud_credential_validation(parent.source, sub)
        if error:
            return {'msg': error}
        return None


class InventorySourceUpdateView(RetrieveAPIView):
    model = models.InventorySource
    obj_permission_type = 'start'
    serializer_class = serializers.InventorySourceUpdateSerializer

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        serializer = self.get_serializer(instance=obj, data=request.data)
        serializer.is_valid(raise_exception=True)
        if obj.can_update:
            update = obj.update()
            if not update:
                return Response({}, status=status.HTTP_400_BAD_REQUEST)
            else:
                headers = {'Location': update.get_absolute_url(request=request)}
                data = OrderedDict()
                data['inventory_update'] = update.id
                data.update(serializers.InventoryUpdateDetailSerializer(update, context=self.get_serializer_context()).to_representation(update))
                return Response(data, status=status.HTTP_202_ACCEPTED, headers=headers)
        else:
            return self.http_method_not_allowed(request, *args, **kwargs)


class InventoryUpdateList(ListAPIView):
    model = models.InventoryUpdate
    serializer_class = serializers.InventoryUpdateListSerializer


class InventoryUpdateDetail(UnifiedJobDeletionMixin, RetrieveDestroyAPIView):
    model = models.InventoryUpdate
    serializer_class = serializers.InventoryUpdateDetailSerializer


class InventoryUpdateCredentialsList(SubListAPIView):
    parent_model = models.InventoryUpdate
    model = models.Credential
    serializer_class = serializers.CredentialSerializer
    relationship = 'credentials'


class InventoryUpdateCancel(GenericCancelView):
    model = models.InventoryUpdate
    serializer_class = serializers.InventoryUpdateCancelSerializer


class InventoryUpdateNotificationsList(SubListAPIView):
    model = models.Notification
    serializer_class = serializers.NotificationSerializer
    parent_model = models.InventoryUpdate
    relationship = 'notifications'
    search_fields = ('subject', 'notification_type', 'body')


class InventoryUpdateStdout(UnifiedJobStdout):
    model = models.InventoryUpdate
