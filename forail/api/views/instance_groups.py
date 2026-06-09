# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

from forail.api.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    ResourceAccessList,
    SubListAPIView,
    SubListAttachDetachAPIView,
)
from forail.api.views.mixin import InstanceGroupMembershipMixin, RelatedJobsPreventDeleteMixin
from forail.api import serializers
from forail.main import models


class InstanceGroupList(ListCreateAPIView):
    name = _("Instance Groups")
    model = models.InstanceGroup
    serializer_class = serializers.InstanceGroupSerializer


class InstanceGroupDetail(RelatedJobsPreventDeleteMixin, RetrieveUpdateDestroyAPIView):
    always_allow_superuser = False
    name = _("Instance Group Detail")
    model = models.InstanceGroup
    serializer_class = serializers.InstanceGroupSerializer

    def update_raw_data(self, data):
        if self.get_object().is_container_group:
            data.pop('policy_instance_percentage', None)
            data.pop('policy_instance_minimum', None)
            data.pop('policy_instance_list', None)
        return super(InstanceGroupDetail, self).update_raw_data(data)


class InstanceGroupUnifiedJobsList(SubListAPIView):
    name = _("Instance Group Running Jobs")
    model = models.UnifiedJob
    serializer_class = serializers.UnifiedJobListSerializer
    parent_model = models.InstanceGroup
    relationship = "unifiedjob_set"


class InstanceGroupAccessList(ResourceAccessList):
    model = models.User  # needs to be User for AccessLists
    parent_model = models.InstanceGroup


class InstanceGroupObjectRolesList(SubListAPIView):
    deprecated = True
    model = models.Role
    serializer_class = serializers.RoleSerializer
    parent_model = models.InstanceGroup
    search_fields = ('role_field', 'content_type__model')

    def get_queryset(self):
        po = self.get_parent_object()
        content_type = ContentType.objects.get_for_model(self.parent_model)
        return models.Role.objects.filter(content_type=content_type, object_id=po.pk)


class InstanceGroupInstanceList(InstanceGroupMembershipMixin, SubListAttachDetachAPIView):
    name = _("Instance Group's Instances")
    model = models.Instance
    serializer_class = serializers.InstanceSerializer
    parent_model = models.InstanceGroup
    relationship = "instances"
    search_fields = ('hostname',)

    def is_valid_relation(self, parent, sub, created=False):
        if sub.node_type == 'control':
            return {'msg': _(f"Cannot change instance group membership of control-only node: {sub.hostname}.")}
        if sub.node_type == 'hop':
            return {'msg': _(f"Cannot change instance group membership of hop node : {sub.hostname}.")}
        return None

    def is_valid_removal(self, parent, sub):
        res = self.is_valid_relation(parent, sub)
        if res:
            return res
        if sub.node_type == 'hybrid' and parent.name == settings.DEFAULT_CONTROL_PLANE_QUEUE_NAME:
            return {'msg': _(f"Cannot disassociate hybrid node {sub.hostname} from {parent.name}.")}
        return None
