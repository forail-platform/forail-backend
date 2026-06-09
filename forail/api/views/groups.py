# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework import status

from forail.api.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    SubListAPIView,
    SubListCreateAttachDetachAPIView,
)
from forail.api.views.mixin import EnforceParentRelationshipMixin, HostRelatedSearchMixin, RelatedJobsPreventDeleteMixin
from forail.api import serializers
from forail.main import models


class GroupList(ListCreateAPIView):
    model = models.Group
    serializer_class = serializers.GroupSerializer


class GroupChildrenList(EnforceParentRelationshipMixin, SubListCreateAttachDetachAPIView):
    model = models.Group
    serializer_class = serializers.GroupSerializer
    parent_model = models.Group
    relationship = 'children'
    enforce_parent_relationship = 'inventory'

    def unattach(self, request, *args, **kwargs):
        sub_id = request.data.get('id', None)
        if sub_id is not None:
            return super(GroupChildrenList, self).unattach(request, *args, **kwargs)
        parent = self.get_parent_object()
        if not request.user.can_access(self.model, 'delete', parent):
            raise PermissionDenied()
        parent.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def is_valid_relation(self, parent, sub, created=False):
        # Prevent any cyclical group associations.
        parent_pks = set(parent.all_parents.values_list('pk', flat=True))
        parent_pks.add(parent.pk)
        child_pks = set(sub.all_children.values_list('pk', flat=True))
        child_pks.add(sub.pk)
        if parent_pks & child_pks:
            return {'error': _('Cyclical Group association.')}
        return None


class GroupPotentialChildrenList(SubListAPIView):
    model = models.Group
    serializer_class = serializers.GroupSerializer
    parent_model = models.Group

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)
        qs = self.request.user.get_queryset(self.model)
        qs = qs.filter(inventory__pk=parent.inventory.pk)
        except_pks = set([parent.pk])
        except_pks.update(parent.all_parents.values_list('pk', flat=True))
        except_pks.update(parent.all_children.values_list('pk', flat=True))
        return qs.exclude(pk__in=except_pks)


class GroupHostsList(HostRelatedSearchMixin, SubListCreateAttachDetachAPIView):
    '''the list of hosts directly below a group'''

    model = models.Host
    serializer_class = serializers.HostSerializer
    parent_model = models.Group
    relationship = 'hosts'

    def update_raw_data(self, data):
        data.pop('inventory', None)
        return super(GroupHostsList, self).update_raw_data(data)

    def create(self, request, *args, **kwargs):
        parent_group = models.Group.objects.get(id=self.kwargs['pk'])
        # Inject parent group inventory ID into new host data.
        request.data['inventory'] = parent_group.inventory_id
        existing_hosts = models.Host.objects.filter(inventory=parent_group.inventory, name=request.data.get('name', ''))
        if existing_hosts.count() > 0 and (
            'variables' not in request.data or request.data['variables'] == '' or request.data['variables'] == '{}' or request.data['variables'] == '---'
        ):
            request.data['id'] = existing_hosts[0].id
            return self.attach(request, *args, **kwargs)
        return super(GroupHostsList, self).create(request, *args, **kwargs)


class GroupAllHostsList(HostRelatedSearchMixin, SubListAPIView):
    '''the list of all hosts below a group, even including subgroups'''

    model = models.Host
    serializer_class = serializers.HostSerializer
    parent_model = models.Group
    relationship = 'hosts'

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)
        qs = self.request.user.get_queryset(self.model).distinct()  # need distinct for '&' operator
        sublist_qs = parent.all_hosts.distinct()
        return qs & sublist_qs


class GroupInventorySourcesList(SubListAPIView):
    model = models.InventorySource
    serializer_class = serializers.InventorySourceSerializer
    parent_model = models.Group
    relationship = 'inventory_sources'


class GroupActivityStreamList(SubListAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
    parent_model = models.Group
    relationship = 'activitystream_set'
    search_fields = ('changes',)

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)
        qs = self.request.user.get_queryset(self.model)
        return qs.filter(Q(group=parent) | Q(host__in=parent.hosts.all()))


class GroupDetail(RelatedJobsPreventDeleteMixin, RetrieveUpdateDestroyAPIView):
    model = models.Group
    serializer_class = serializers.GroupSerializer

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if not request.user.can_access(self.model, 'delete', obj):
            raise PermissionDenied()
        obj.delete_recursive()
        return Response(status=status.HTTP_204_NO_CONTENT)
