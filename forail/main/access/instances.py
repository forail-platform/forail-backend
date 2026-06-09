# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.conf import settings

from forail.main.access.base import BaseAccess, check_superuser
from forail.main.models import (
    Instance,
    InstanceGroup,
    ReceptorAddress,
)


class InstanceAccess(BaseAccess):
    model = Instance
    prefetch_related = ('rampart_groups',)

    def filtered_queryset(self):
        return Instance.objects.filter(rampart_groups__in=self.user.get_queryset(InstanceGroup)).distinct()

    def can_attach(self, obj, sub_obj, relationship, data, skip_sub_obj_read_check=False):
        if relationship == 'rampart_groups' and isinstance(sub_obj, InstanceGroup):
            return self.user.is_superuser
        return super(InstanceAccess, self).can_attach(obj, sub_obj, relationship, data, skip_sub_obj_read_check=skip_sub_obj_read_check)

    def can_unattach(self, obj, sub_obj, relationship, data=None):
        if relationship == 'rampart_groups' and isinstance(sub_obj, InstanceGroup):
            return self.user.is_superuser
        return super(InstanceAccess, self).can_unattach(obj, sub_obj, relationship, relationship, data=data)

    def can_add(self, data):
        return self.user.is_superuser

    def can_change(self, obj, data):
        return False

    def can_delete(self, obj):
        return False


class InstanceGroupAccess(BaseAccess):
    """
    I can see Instance Groups when I am:
       - a superuser(system administrator)
       - at least read_role on the instance group
    I can edit Instance Groups when I am:
       - a superuser
       - admin role on the Instance group
    I can add/delete Instance Groups:
       - a superuser(system administrator), because these are not org-scoped
    I can use Instance Groups when I have:
       - use_role on the instance group
    """

    model = InstanceGroup
    prefetch_related = ('instances',)

    def filtered_queryset(self):
        return self.model.accessible_objects(self.user, 'read_role')

    @check_superuser
    def can_use(self, obj):
        return self.user in obj.use_role

    def can_add(self, data):
        return self.user.is_superuser

    @check_superuser
    def can_change(self, obj, data):
        return self.can_admin(obj)

    @check_superuser
    def can_admin(self, obj):
        return self.user in obj.admin_role

    def can_delete(self, obj):
        if obj.name in [settings.DEFAULT_EXECUTION_QUEUE_NAME, settings.DEFAULT_CONTROL_PLANE_QUEUE_NAME]:
            return False
        return self.user.has_obj_perm(obj, 'delete')


class ReceptorAddressAccess(BaseAccess):
    """
    I can see receptor address records whenever I can access the instance
    """

    model = ReceptorAddress

    def filtered_queryset(self):
        from django.db.models import Q
        return self.model.objects.filter(Q(instance__in=Instance.accessible_pk_qs(self.user, 'read_role')))

    @check_superuser
    def can_add(self, data):
        return False

    @check_superuser
    def can_change(self, obj, data):
        return False

    @check_superuser
    def can_delete(self, obj):
        return False
