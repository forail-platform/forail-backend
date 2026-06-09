# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.db.models import Prefetch
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import ParseError, PermissionDenied

from forail.main.access.base import (
    BaseAccess,
    NotificationAttachMixin,
    UnifiedCredentialsMixin,
    check_superuser,
    get_pk_from_dict,
)
from forail.main.models import (
    Group,
    Host,
    Inventory,
    InventorySource,
    InventoryUpdate,
    Label,
    Project,
)


class InventoryAccess(BaseAccess):
    """
    I can see inventory when:
     - I'm a superuser.
     - I'm an org admin of the inventory's org.
     - I'm an inventory admin of the inventory's org.
     - I have read, write or admin permissions on it.
    I can change inventory when:
     - I'm a superuser.
     - I'm an org admin of the inventory's org.
     - I have write or admin permissions on it.
    I can delete inventory when:
     - I'm a superuser.
     - I'm an org admin of the inventory's org.
     - I have admin permissions on it.
    I can run ad hoc commands when:
     - I'm a superuser.
     - I'm an org admin of the inventory's org.
     - I have read/write/admin permission on an inventory with the run_ad_hoc_commands flag set.
    """

    model = Inventory
    prefetch_related = (
        'created_by',
        'modified_by',
        'organization',
        Prefetch('labels', queryset=Label.objects.all().order_by('name')),
    )

    def filtered_queryset(self, allowed=None, ad_hoc=None):
        return self.model.accessible_objects(self.user, 'read_role')

    @check_superuser
    def can_use(self, obj):
        return self.user in obj.use_role

    @check_superuser
    def can_add(self, data):
        # If no data is specified, just checking for generic add permission?
        if not data:
            return Organization.accessible_objects(self.user, 'inventory_admin_role').exists()
        return self.check_related('organization', Organization, data, role_field='inventory_admin_role')

    @check_superuser
    def can_change(self, obj, data):
        return self.can_admin(obj, data)

    @check_superuser
    def can_admin(self, obj, data):
        # Host filter may only be modified by org admin level
        org_admin_mandatory = False
        new_host_filter = data.get('host_filter', None) if data else None
        if new_host_filter and new_host_filter != obj.host_filter:
            org_admin_mandatory = True
        # Verify that the user has access to the new organization if moving an
        # inventory to a new organization.  Otherwise, just check for admin permission.
        return (
            self.check_related('organization', Organization, data, obj=obj, role_field='inventory_admin_role', mandatory=org_admin_mandatory)
            and self.user in obj.admin_role
        )

    @check_superuser
    def can_update(self, obj):
        return self.user in obj.update_role

    def can_run_ad_hoc_commands(self, obj):
        return self.user in obj.adhoc_role

    def can_attach(self, obj, sub_obj, relationship, *args, **kwargs):
        if relationship == "instance_groups":
            if self.user in sub_obj.use_role and self.user in obj.admin_role:
                return True
            return False
        return super(InventoryAccess, self).can_attach(obj, sub_obj, relationship, *args, **kwargs)

    def can_unattach(self, obj, sub_obj, relationship, *args, **kwargs):
        if relationship == "instance_groups":
            return self.can_attach(obj, sub_obj, relationship, *args, **kwargs)
        return super(InventoryAccess, self).can_attach(obj, sub_obj, relationship, *args, **kwargs)


# Needed for InventoryAccess.can_add
from forail.main.models import Organization  # noqa: E402


class HostAccess(BaseAccess):
    """
    I can see hosts whenever I can see their inventory.
    I can change or delete hosts whenver I can change their inventory.
    """

    model = Host
    select_related = (
        'created_by',
        'modified_by',
        'inventory',
        'last_job__job_template',
        'last_job_host_summary__job',
    )
    prefetch_related = ('groups', 'inventory_sources')

    def filtered_queryset(self):
        return self.model.objects.filter(inventory__in=Inventory.accessible_pk_qs(self.user, 'read_role'))

    def can_add(self, data):
        if not data:  # So the browseable API will work
            return Inventory.accessible_objects(self.user, 'admin_role').exists()

        # Checks for admin or change permission on inventory.
        if not self.check_related('inventory', Inventory, data):
            return False

        # Check to see if we have enough licenses
        self.check_license(add_host_name=data.get('name', None))

        # Check the per-org limit
        self.check_org_host_limit(data, add_host_name=data.get('name', None))

        return True

    def can_change(self, obj, data):
        # Prevent moving a host to a different inventory.
        inventory_pk = get_pk_from_dict(data, 'inventory')
        if obj and inventory_pk and obj.inventory.pk != inventory_pk:
            raise PermissionDenied(_('Unable to change inventory on a host.'))

        # Prevent renaming a host that might exceed license count
        if data and 'name' in data:
            self.check_license(add_host_name=data['name'])

        # Checks for admin or change permission on inventory, controls whether
        # the user can edit variable data.
        return obj and self.user in obj.inventory.admin_role

    def can_attach(self, obj, sub_obj, relationship, data, skip_sub_obj_read_check=False):
        if not super(HostAccess, self).can_attach(obj, sub_obj, relationship, data, skip_sub_obj_read_check):
            return False
        # Prevent assignments between different inventories.
        if obj.inventory != sub_obj.inventory:
            raise ParseError(_('Cannot associate two items from different inventories.'))
        return True

    def can_delete(self, obj):
        return obj and self.user in obj.inventory.admin_role


class GroupAccess(BaseAccess):
    """
    I can see groups whenever I can see their inventory.
    I can change or delete groups whenever I can change their inventory.
    """

    model = Group
    select_related = (
        'created_by',
        'modified_by',
        'inventory',
    )
    prefetch_related = (
        'parents',
        'children',
    )

    def filtered_queryset(self):
        return Group.objects.filter(inventory__in=Inventory.accessible_pk_qs(self.user, 'read_role'))

    def can_add(self, data):
        if not data:  # So the browseable API will work
            return Inventory.accessible_objects(self.user, 'admin_role').exists()
        if 'inventory' not in data:
            return False
        # Checks for admin or change permission on inventory.
        return self.check_related('inventory', Inventory, data)

    def can_change(self, obj, data):
        # Prevent moving a group to a different inventory.
        inventory_pk = get_pk_from_dict(data, 'inventory')
        if obj and inventory_pk and obj.inventory.pk != inventory_pk:
            raise PermissionDenied(_('Unable to change inventory on a group.'))
        # Checks for admin or change permission on inventory, controls whether
        # the user can attach subgroups or edit variable data.
        return obj and self.user in obj.inventory.admin_role

    def can_attach(self, obj, sub_obj, relationship, data, skip_sub_obj_read_check=False):
        if not super(GroupAccess, self).can_attach(obj, sub_obj, relationship, data, skip_sub_obj_read_check):
            return False
        # Prevent assignments between different inventories.
        if obj.inventory != sub_obj.inventory:
            raise ParseError(_('Cannot associate two items from different inventories.'))
        return True

    def can_delete(self, obj):
        return bool(obj and self.user in obj.inventory.admin_role)


class InventorySourceAccess(NotificationAttachMixin, UnifiedCredentialsMixin, BaseAccess):
    """
    I can see inventory sources whenever I can see their inventory.
    I can change inventory sources whenever I can change their inventory.
    """

    model = InventorySource
    select_related = ('created_by', 'modified_by', 'inventory')
    prefetch_related = ('credentials__credential_type', 'last_job', 'source_project')

    def filtered_queryset(self):
        return self.model.objects.filter(inventory__in=Inventory.accessible_pk_qs(self.user, 'read_role'))

    def can_add(self, data):
        if not data or 'inventory' not in data:
            return Inventory.accessible_objects(self.user, 'admin_role').exists()

        if not self.check_related('source_project', Project, data, role_field='use_role'):
            return False
        # Checks for admin or change permission on inventory.
        return self.check_related('inventory', Inventory, data)

    def can_delete(self, obj):
        if not self.user.is_superuser and not (obj and obj.inventory and self.user.can_access(Inventory, 'admin', obj.inventory, None)):
            return False
        return True

    @check_superuser
    def can_change(self, obj, data):
        # Checks for admin change permission on inventory.
        if obj and obj.inventory:
            return self.user.can_access(Inventory, 'change', obj.inventory, None) and self.check_related(
                'source_project', Project, data, obj=obj, role_field='use_role'
            )
        # Can't change inventory sources attached to only the inventory, since
        # these are created automatically from the management command.
        else:
            return False

    def can_start(self, obj, validate_license=True):
        if obj and obj.inventory:
            return self.user in obj.inventory.update_role
        return False


class InventoryUpdateAccess(BaseAccess):
    """
    I can see inventory updates when I can see the inventory source.
    I can change inventory updates whenever I can change their source.
    I can delete when I can change/delete the inventory source.
    """

    model = InventoryUpdate
    select_related = (
        'created_by',
        'modified_by',
        'inventory_source',
    )
    prefetch_related = ('unified_job_template', 'instance_group', 'credentials__credential_type', 'inventory')

    def filtered_queryset(self):
        return self.model.objects.filter(inventory_source__inventory__in=Inventory.accessible_pk_qs(self.user, 'read_role'))

    def can_cancel(self, obj):
        if not obj.can_cancel:
            return False
        if self.user.is_superuser or self.user == obj.created_by:
            return True
        # Inventory cascade deletes to inventory update, descends from org admin
        return self.user in obj.inventory_source.inventory.admin_role

    def can_start(self, obj, validate_license=True):
        return InventorySourceAccess(self.user).can_start(obj, validate_license=validate_license)

    @check_superuser
    def can_delete(self, obj):
        return self.user in obj.inventory_source.inventory.admin_role
