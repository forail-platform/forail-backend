# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.http import HttpResponseRedirect
from django.utils.translation import gettext_lazy as _

from rest_framework.response import Response
from rest_framework import status

from forail.main.utils.filters import SmartFilter
from forail.api.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveDestroyAPIView,
    RetrieveUpdateDestroyAPIView,
    SubListAPIView,
    SubListCreateAttachDetachAPIView,
)
from forail.api.views.mixin import HostRelatedSearchMixin, RelatedJobsPreventDeleteMixin
from forail.api.permissions import IsSystemAdminOrAuditor
from forail.api.versioning import reverse
from forail.api import serializers
from forail.main import models


class HostMetricList(ListAPIView):
    name = _("Host Metrics List")
    model = models.HostMetric
    serializer_class = serializers.HostMetricSerializer
    permission_classes = (IsSystemAdminOrAuditor,)
    search_fields = ('hostname', 'deleted')

    def get_queryset(self):
        return self.model.objects.all()


class HostMetricDetail(RetrieveDestroyAPIView):
    name = _("Host Metric Detail")
    model = models.HostMetric
    serializer_class = serializers.HostMetricSerializer
    permission_classes = (IsSystemAdminOrAuditor,)

    def delete(self, request, *args, **kwargs):
        self.get_object().soft_delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class HostMetricSummaryMonthlyList(ListAPIView):
    name = _("Host Metrics Summary Monthly")
    model = models.HostMetricSummaryMonthly
    serializer_class = serializers.HostMetricSummaryMonthlySerializer
    permission_classes = (IsSystemAdminOrAuditor,)
    search_fields = ('date',)

    def get_queryset(self):
        return self.model.objects.all()


class HostList(HostRelatedSearchMixin, ListCreateAPIView):
    always_allow_superuser = False
    model = models.Host
    serializer_class = serializers.HostSerializer

    def get_queryset(self):
        qs = super(HostList, self).get_queryset()
        filter_string = self.request.query_params.get('host_filter', None)
        if filter_string:
            filter_qs = SmartFilter.query_from_string(filter_string)
            qs &= filter_qs
        return qs.distinct()

    def list(self, *args, **kwargs):
        try:
            return super(HostList, self).list(*args, **kwargs)
        except Exception as e:
            return Response(dict(error=_(str(e))), status=status.HTTP_400_BAD_REQUEST)


class HostDetail(RelatedJobsPreventDeleteMixin, RetrieveUpdateDestroyAPIView):
    always_allow_superuser = False
    model = models.Host
    serializer_class = serializers.HostSerializer

    def delete(self, request, *args, **kwargs):
        if self.get_object().inventory.pending_deletion:
            return Response({"error": _("The inventory for this host is already being deleted.")}, status=status.HTTP_400_BAD_REQUEST)
        if self.get_object().inventory.kind == 'constructed':
            return Response({"error": _("Delete constructed inventory hosts from input inventory.")}, status=status.HTTP_400_BAD_REQUEST)
        return super(HostDetail, self).delete(request, *args, **kwargs)


class HostAnsibleFactsDetail(RetrieveAPIView):
    model = models.Host
    serializer_class = serializers.AnsibleFactsSerializer

    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.inventory.kind == 'constructed':
            # If this is a constructed inventory host, it is not the source of truth about facts
            # redirect to the original input inventory host instead
            return HttpResponseRedirect(reverse('api:host_ansible_facts_detail', kwargs={'pk': obj.instance_id}, request=self.request))
        return super().get(request, *args, **kwargs)


class InventoryHostsList(HostRelatedSearchMixin, SubListCreateAttachDetachAPIView):
    model = models.Host
    serializer_class = serializers.HostSerializer
    parent_model = models.Inventory
    relationship = 'hosts'
    parent_key = 'inventory'
    filter_read_permission = False


class HostGroupsList(SubListCreateAttachDetachAPIView):
    '''the list of groups a host is directly a member of'''

    model = models.Group
    serializer_class = serializers.GroupSerializer
    parent_model = models.Host
    relationship = 'groups'

    def update_raw_data(self, data):
        data.pop('inventory', None)
        return super(HostGroupsList, self).update_raw_data(data)

    def create(self, request, *args, **kwargs):
        # Inject parent host inventory ID into new group data.
        data = request.data
        # HACK: Make request data mutable.
        if getattr(data, '_mutable', None) is False:
            data._mutable = True
        data['inventory'] = self.get_parent_object().inventory_id
        return super(HostGroupsList, self).create(request, *args, **kwargs)


class HostAllGroupsList(SubListAPIView):
    '''the list of all groups of which the host is directly or indirectly a member'''

    model = models.Group
    serializer_class = serializers.GroupSerializer
    parent_model = models.Host
    relationship = 'groups'

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)
        qs = self.request.user.get_queryset(self.model).distinct()
        sublist_qs = parent.all_groups.distinct()
        return qs & sublist_qs


class HostInventorySourcesList(SubListAPIView):
    model = models.InventorySource
    serializer_class = serializers.InventorySourceSerializer
    parent_model = models.Host
    relationship = 'inventory_sources'


class HostSmartInventoriesList(SubListAPIView):
    model = models.Inventory
    serializer_class = serializers.InventorySerializer
    parent_model = models.Host
    relationship = 'smart_inventories'


class HostActivityStreamList(SubListAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
    parent_model = models.Host
    relationship = 'activitystream_set'
    search_fields = ('changes',)

    def get_queryset(self):
        from django.db.models import Q

        parent = self.get_parent_object()
        self.check_parent_access(parent)
        qs = self.request.user.get_queryset(self.model)
        return qs.filter(Q(host=parent) | Q(inventory=parent.inventory))
