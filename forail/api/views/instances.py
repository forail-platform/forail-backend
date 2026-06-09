# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.conf import settings
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from rest_framework.response import Response
from rest_framework import status

from forail.main.access import get_user_queryset
from forail.api.generics import (
    GenericAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateAPIView,
    SubListAPIView,
    SubListCreateAttachDetachAPIView,
    ListAPIView,
)
from forail.api.views.mixin import InstanceGroupMembershipMixin
from forail.api.permissions import IsSystemAdminOrAuditor
from forail.api import serializers
from forail.main import models


class InstanceList(ListCreateAPIView):
    name = _("Instances")
    model = models.Instance
    serializer_class = serializers.InstanceSerializer
    search_fields = ('hostname',)
    ordering = ('id',)

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related('receptor_addresses')
        return qs


class InstanceDetail(RetrieveUpdateAPIView):
    name = _("Instance Detail")
    model = models.Instance
    serializer_class = serializers.InstanceSerializer

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related('receptor_addresses')
        return qs

    def update_raw_data(self, data):
        # these fields are only valid on creation of an instance, so they unwanted on detail view
        data.pop('node_type', None)
        data.pop('hostname', None)
        data.pop('ip_address', None)
        return super(InstanceDetail, self).update_raw_data(data)

    def update(self, request, *args, **kwargs):
        r = super(InstanceDetail, self).update(request, *args, **kwargs)
        if status.is_success(r.status_code):
            obj = self.get_object()
            capacity_changed = obj.set_capacity_value()
            if capacity_changed:
                obj.save(update_fields=['capacity'])
            r.data = serializers.InstanceSerializer(obj, context=self.get_serializer_context()).to_representation(obj)
        return r


class InstanceUnifiedJobsList(SubListAPIView):
    name = _("Instance Jobs")
    model = models.UnifiedJob
    serializer_class = serializers.UnifiedJobListSerializer
    parent_model = models.Instance

    def get_queryset(self):
        po = self.get_parent_object()
        qs = get_user_queryset(self.request.user, models.UnifiedJob)
        qs = qs.filter(execution_node=po.hostname)
        return qs


class InstancePeersList(SubListAPIView):
    name = _("Peers")
    model = models.ReceptorAddress
    serializer_class = serializers.ReceptorAddressSerializer
    parent_model = models.Instance
    parent_access = 'read'
    relationship = 'peers'
    search_fields = ('address',)


class InstanceReceptorAddressesList(SubListAPIView):
    name = _("Receptor Addresses")
    model = models.ReceptorAddress
    parent_key = 'instance'
    parent_model = models.Instance
    serializer_class = serializers.ReceptorAddressSerializer
    search_fields = ('address',)


class ReceptorAddressesList(ListAPIView):
    name = _("Receptor Addresses")
    model = models.ReceptorAddress
    serializer_class = serializers.ReceptorAddressSerializer
    search_fields = ('address',)


class ReceptorAddressDetail(RetrieveAPIView):
    name = _("Receptor Address Detail")
    model = models.ReceptorAddress
    serializer_class = serializers.ReceptorAddressSerializer
    parent_model = models.Instance
    relationship = 'receptor_addresses'


class InstanceInstanceGroupsList(InstanceGroupMembershipMixin, SubListCreateAttachDetachAPIView):
    name = _("Instance's Instance Groups")
    model = models.InstanceGroup
    serializer_class = serializers.InstanceGroupSerializer
    parent_model = models.Instance
    relationship = 'rampart_groups'

    def is_valid_relation(self, parent, sub, created=False):
        if parent.node_type == 'control':
            return {'msg': _(f"Cannot change instance group membership of control-only node: {parent.hostname}.")}
        if parent.node_type == 'hop':
            return {'msg': _(f"Cannot change instance group membership of hop node : {parent.hostname}.")}
        return None

    def is_valid_removal(self, parent, sub):
        res = self.is_valid_relation(parent, sub)
        if res:
            return res
        if sub.name == settings.DEFAULT_CONTROL_PLANE_QUEUE_NAME and parent.node_type == 'hybrid':
            return {'msg': _(f"Cannot disassociate hybrid instance {parent.hostname} from {sub.name}.")}
        return None


class InstanceHealthCheck(GenericAPIView):
    name = _('Instance Health Check')
    model = models.Instance
    serializer_class = serializers.InstanceHealthCheckSerializer
    permission_classes = (IsSystemAdminOrAuditor,)

    def get_queryset(self):
        return super().get_queryset().filter(node_type='execution')
        # FIXME: For now, we don't have a good way of checking the health of a hop node.

    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        data = self.get_serializer(data=request.data).to_representation(obj)
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.health_check_pending:
            return Response({'msg': f"Health check was already in progress for {obj.hostname}."}, status=status.HTTP_200_OK)

        # Note: hop nodes are already excluded by the get_queryset method
        obj.health_check_started = now()
        obj.save(update_fields=['health_check_started'])
        if obj.node_type == models.Instance.Types.EXECUTION:
            from forail.main.tasks.system import execution_node_health_check

            execution_node_health_check.apply_async([obj.hostname])
        else:
            return Response(
                {"error": f"Cannot run a health check on instances of type {obj.node_type}.  Health checks can only be run on execution nodes."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'msg': f"Health check is running for {obj.hostname}."}, status=status.HTTP_200_OK)
