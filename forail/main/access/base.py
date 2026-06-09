# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Python
import os
import sys
import logging

# Django
from django.conf import settings
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ObjectDoesNotExist, FieldDoesNotExist

# Django REST Framework
from rest_framework.exceptions import ParseError, PermissionDenied

# django-ansible-base
from ansible_base.rbac import permission_registry

# AWX
from forail.main.utils import (
    get_object_or_400,
    get_licenser,
)
from forail.main.utils import get_pk_from_dict  # noqa: F401
from forail.main.models import (
    Credential,
    CredentialInputSource,
    ExecutionEnvironment,
    Group,
    Host,
    InstanceGroup,
    Inventory,
    JobTemplate,
    NotificationTemplate,
    Project,
    Team,
    UnifiedJob,
    WorkflowJobTemplate,
)

__all__ = [
    'get_user_queryset',
    'check_user_access',
    'check_user_access_with_errors',
]

logger = logging.getLogger('forail.main.access')

access_registry = {
    # <model_class>: <access_class>,
    # ...
}


def get_object_from_data(field, Model, data, obj=None):
    """
    Utility method to obtain related object in data according to fallbacks:
     - if data contains key with pointer to Django object, return that
     - if contains integer, get object from database
     - if this does not work, raise exception
    """
    try:
        raw_value = data[field]
    except KeyError:
        # Calling method needs to deal with non-existence of key
        raise ParseError(_("Required related field %s for permission check." % field))

    try:
        if isinstance(raw_value, Model):
            return raw_value
        elif raw_value is None:
            return None
        else:
            new_pk = int(raw_value)
            # Avoid database query by comparing pk to model for similarity
            if obj and new_pk == getattr(obj, '%s_id' % field, None):
                return getattr(obj, field)
            else:
                # Get the new resource from the database
                return get_object_or_400(Model, pk=new_pk)
    except (TypeError, ValueError):
        raise ParseError(_("Bad data found in related field %s." % field))


def vars_are_encrypted(vars):
    """Returns True if any of the values in the dictionary vars contains
    content which is encrypted by the AWX encryption algorithm
    """
    for value in vars.values():
        if isinstance(value, str):
            if value.startswith('$encrypted$'):
                return True
    return False


def register_access(model_class, access_class):
    access_registry[model_class] = access_class


def get_user_queryset(user, model_class):
    """
    Return a queryset for the given model_class containing only the instances
    that should be visible to the given user.
    """
    access_class = access_registry[model_class]
    access_instance = access_class(user)
    return access_instance.get_queryset()


def check_user_access(user, model_class, action, *args, **kwargs):
    """
    Return True if user can perform action against model_class with the
    provided parameters.
    """
    access_class = access_registry[model_class]
    access_instance = access_class(user)
    access_method = getattr(access_instance, 'can_%s' % action)
    result = access_method(*args, **kwargs)
    logger.debug('%s.%s %r returned %r', access_instance.__class__.__name__, getattr(access_method, '__name__', 'unknown'), args, result)
    return result


def check_user_access_with_errors(user, model_class, action, *args, **kwargs):
    """
    Return T/F permission and summary of problems with the action.
    """
    access_class = access_registry[model_class]
    access_instance = access_class(user, save_messages=True)
    access_method = getattr(access_instance, 'can_%s' % action, None)
    result = access_method(*args, **kwargs)
    logger.debug('%s.%s %r returned %r', access_instance.__class__.__name__, access_method.__name__, args, result)
    return (result, access_instance.messages)


def get_user_capabilities(user, instance, **kwargs):
    """
    Returns a dictionary of capabilities the user has on the particular
    instance.  *NOTE* This is not a direct mapping of can_* methods into this
    dictionary, it is intended to munge some queries in a way that is
    convenient for the user interface to consume and hide or show various
    actions in the interface.
    """
    access_class = access_registry[instance.__class__]
    return access_class(user).get_user_capabilities(instance, **kwargs)


def check_superuser(func):
    """
    check_superuser is a decorator that provides a simple short circuit
    for access checks. If the User object is a superuser, return True, otherwise
    execute the logic of the can_access method.
    """

    def wrapper(self, *args, **kwargs):
        if self.user.is_superuser:
            return True
        return func(self, *args, **kwargs)

    return wrapper


class BaseAccess(object):
    """
    Base class for checking user access to a given model.  Subclasses should
    define the model attribute, override the get_queryset method to return only
    the instances the user should be able to view, and override/define can_*
    methods to verify a user's permission to perform a particular action.
    """

    model = None
    select_related = ()
    prefetch_related = ()

    def __init__(self, user, save_messages=False):
        self.user = user
        self.save_messages = save_messages
        if save_messages:
            self.messages = {}

    def get_queryset(self):
        if self.user.is_superuser or self.user.is_system_auditor:
            qs = self.model.objects.all()
        else:
            qs = self.filtered_queryset()

        # Apply queryset optimizations
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        if self.prefetch_related:
            qs = qs.prefetch_related(*self.prefetch_related)

        return qs

    def filtered_queryset(self):
        # Override in subclasses
        # filter objects according to user's read access
        return self.model.objects.none()

    def can_read(self, obj):
        return bool(obj and self.get_queryset().filter(pk=obj.pk).exists())

    def can_add(self, data):
        return self.user.is_superuser

    def can_change(self, obj, data):
        return self.user.is_superuser

    def can_write(self, obj, data):
        # Alias for change.
        return self.can_change(obj, data)

    def can_admin(self, obj, data):
        # Alias for can_change.  Can be overridden if admin vs. user change
        # permissions need to be different.
        return self.can_change(obj, data)

    def can_delete(self, obj):
        if self.user.is_superuser:
            return True
        if obj._meta.model_name in [cls._meta.model_name for cls in permission_registry.all_registered_models]:
            return self.user.has_obj_perm(obj, 'delete')
        return False

    def can_copy(self, obj):
        return self.can_add({'reference_obj': obj})

    def can_copy_related(self, obj):
        """
        can_copy_related() should only be used to check if the user have access to related
        many to many credentials in when copying the object. It does not check if the user
        has permission for any other related objects. Therefore, when checking if the user
        can copy an object, it should always be used in conjunction with can_add()
        """
        return True

    def assure_relationship_exists(self, obj, relationship):
        if '.' in relationship:
            return  # not attempting validation for complex relationships now
        try:
            obj._meta.get_field(relationship)
        except FieldDoesNotExist:
            raise NotImplementedError(f'The relationship {relationship} does not exist for model {type(obj)}')

    def can_attach(self, obj, sub_obj, relationship, data, skip_sub_obj_read_check=False):
        self.assure_relationship_exists(obj, relationship)
        if skip_sub_obj_read_check:
            return self.can_change(obj, None)
        else:
            return bool(self.can_change(obj, None) and self.user.can_access(type(sub_obj), 'read', sub_obj))

    def can_unattach(self, obj, sub_obj, relationship, data=None):
        self.assure_relationship_exists(obj, relationship)
        return self.can_change(obj, data)

    def check_related(self, field, Model, data, role_field='admin_role', obj=None, mandatory=False):
        """
        Check permission for related field, in scenarios:
         - creating a new resource, user must have permission if
           resource is specified in `data`
         - editing an existing resource, user must have permission to resource
           in `data`, as well as existing related resource on `obj`

        If `mandatory` is set, new resources require the field and
                               existing field will always be checked
        """
        new = None
        changed = True
        if data and 'reference_obj' in data:
            # Use reference object's related fields, if given
            new = getattr(data['reference_obj'], field)
        elif data and field in data:
            new = get_object_from_data(field, Model, data, obj=obj)
        else:
            changed = False

        # Obtain existing related resource
        current = None
        if obj and (changed or mandatory):
            current = getattr(obj, field)

        if obj and new == current:
            # Resource not changed, like a PUT request
            changed = False

        if (not new) and (not obj) and mandatory:
            # Restrict ability to create resource without required field
            return self.user.is_superuser

        def user_has_resource_access(resource):
            role = getattr(resource, role_field, None)
            if role is None:
                # Handle special case where resource does not have direct roles
                if role_field == 'read_role':
                    return self.user.can_access(type(resource), 'read', resource)
                access_method_type = {'admin_role': 'change', 'execute_role': 'start'}[role_field]
                return self.user.can_access(type(resource), access_method_type, resource, None)
            return self.user in role

        if new and changed and (not user_has_resource_access(new)):
            return False  # User lacks access to provided resource

        if current and (changed or mandatory) and (not user_has_resource_access(current)):
            return False  # User lacks access to existing resource

        return True  # User has access to both, permission check passed

    def check_license(self, add_host_name=None, feature=None, check_expiration=True, quiet=False):
        validation_info = get_licenser().validate()
        if validation_info.get('license_type', 'UNLICENSED') == 'open':
            return

        if ('test' in sys.argv or 'py.test' in sys.argv[0] or 'jenkins' in sys.argv) and not os.environ.get('SKIP_LICENSE_FIXUP_FOR_TEST', ''):
            validation_info['free_instances'] = 99999999
            validation_info['time_remaining'] = 99999999
            validation_info['grace_period_remaining'] = 99999999

        if quiet:
            report_violation = lambda message: None
        else:
            report_violation = lambda message: logger.warning(message)
        if validation_info.get('trial', False) is True:

            def report_violation(message):  # noqa
                raise PermissionDenied(message)

        if check_expiration and validation_info.get('time_remaining', None) is None:
            raise PermissionDenied(_("License is missing."))
        elif check_expiration and validation_info.get("grace_period_remaining") <= 0:
            report_violation(_("License has expired."))

        free_instances = validation_info.get('free_instances', 0)
        instance_count = validation_info.get('instance_count', 0)

        if add_host_name:
            host_exists = Host.objects.filter(name=add_host_name).exists()
            if not host_exists and free_instances == 0:
                report_violation(_("License count of %s instances has been reached.") % instance_count)
            elif not host_exists and free_instances < 0:
                report_violation(_("License count of %s instances has been exceeded.") % instance_count)
        elif not add_host_name and free_instances < 0:
            report_violation(_("Host count exceeds available instances."))

    def check_org_host_limit(self, data, add_host_name=None):
        validation_info = get_licenser().validate()
        if validation_info.get('license_type', 'UNLICENSED') == 'open':
            return

        inventory = get_object_from_data('inventory', Inventory, data)
        if inventory is None:  # In this case a missing inventory error is launched
            return  # further down the line, so just ignore it.

        org = inventory.organization
        if org is None or org.max_hosts == 0:
            return

        active_count = Host.objects.org_active_count(org.id)
        if active_count > org.max_hosts:
            raise PermissionDenied(
                _(
                    "You have already reached the maximum number of %s hosts"
                    " allowed for your organization. Contact your System Administrator"
                    " for assistance." % org.max_hosts
                )
            )

        if add_host_name:
            host_exists = Host.objects.filter(inventory__organization=org.id, name=add_host_name).exists()
            if not host_exists and active_count == org.max_hosts:
                raise PermissionDenied(
                    _(
                        "You have already reached the maximum number of %s hosts"
                        " allowed for your organization. Contact your System Administrator"
                        " for assistance." % org.max_hosts
                    )
                )

    def get_user_capabilities(self, obj, method_list=[], parent_obj=None, capabilities_cache={}):
        if obj is None:
            return {}
        user_capabilities = {}

        # Custom ordering to loop through methods so we can reuse earlier calcs
        for display_method in ['edit', 'delete', 'start', 'schedule', 'copy', 'adhoc', 'unattach']:
            if display_method not in method_list:
                continue

            if not settings.MANAGE_ORGANIZATION_AUTH and isinstance(obj, (Team, User)):
                user_capabilities[display_method] = self.user.is_superuser
                continue

            # Actions not possible for reason unrelated to RBAC
            # Cannot copy with validation errors, or update a manual group/project
            if 'write' not in getattr(self.user, 'oauth_scopes', ['write']):
                user_capabilities[display_method] = False  # Read tokens cannot take any actions
                continue
            elif display_method in ['copy', 'start', 'schedule'] and isinstance(obj, JobTemplate):
                if obj.validation_errors:
                    user_capabilities[display_method] = False
                    continue
            elif display_method == 'copy' and isinstance(obj, WorkflowJobTemplate) and obj.organization_id is None:
                user_capabilities[display_method] = self.user.is_superuser
                continue
            elif display_method == 'copy' and isinstance(obj, Project) and obj.scm_type == '':
                # Cannot copy manual project without errors
                user_capabilities[display_method] = False
                continue
            elif display_method in ['start', 'schedule'] and isinstance(obj, (Project)):
                if obj.scm_type == '':
                    user_capabilities[display_method] = False
                    continue

            # Grab the answer from the cache, if available
            if display_method in capabilities_cache:
                user_capabilities[display_method] = capabilities_cache[display_method]
                if self.user.is_superuser and not user_capabilities[display_method]:
                    # Cache override for models with bad orphaned state
                    user_capabilities[display_method] = True
                continue

            # Aliases for going form UI language to API language
            if display_method == 'edit':
                method = 'change'
            elif display_method == 'adhoc':
                method = 'run_ad_hoc_commands'
            else:
                method = display_method

            # Shortcuts in certain cases by deferring to earlier property
            if display_method == 'schedule':
                user_capabilities['schedule'] = user_capabilities['start']
                continue
            elif display_method == 'delete' and not isinstance(obj, (User, UnifiedJob, CredentialInputSource, ExecutionEnvironment, InstanceGroup)):
                user_capabilities['delete'] = user_capabilities['edit']
                continue
            elif display_method == 'copy' and isinstance(obj, (Group, Host)):
                user_capabilities['copy'] = user_capabilities['edit']
                continue

            # Compute permission
            user_capabilities[display_method] = self.get_method_capability(method, obj, parent_obj)

        return user_capabilities

    def get_method_capability(self, method, obj, parent_obj):
        try:
            if method in ['change']:  # 3 args
                return self.can_change(obj, {})
            elif method in ['delete', 'run_ad_hoc_commands', 'copy']:
                access_method = getattr(self, "can_%s" % method)
                return access_method(obj)
            elif method in ['start']:
                return self.can_start(obj, validate_license=False)
            elif method in ['attach', 'unattach']:  # parent/sub-object call
                access_method = getattr(self, "can_%s" % method)
                if type(parent_obj) == Team:
                    relationship = 'parents'
                    parent_obj = parent_obj.member_role
                else:
                    relationship = 'members'
                return access_method(obj, parent_obj, relationship, skip_sub_obj_read_check=True, data={})
        except (ParseError, ObjectDoesNotExist, PermissionDenied):
            return False
        return False


class UnifiedCredentialsMixin(BaseAccess):
    """
    The credentials many-to-many is a standard relationship for JT, jobs, and others
    Permission to attach is always use permission, and permission to unattach is admin to the parent object
    """

    @check_superuser
    def can_attach(self, obj, sub_obj, relationship, data, skip_sub_obj_read_check=False):
        if relationship == 'credentials':
            if not isinstance(sub_obj, Credential):
                raise RuntimeError(f'Can only attach credentials to credentials relationship, got {type(sub_obj)}')
            return self.can_change(obj, None) and (self.user in sub_obj.use_role)
        return super().can_attach(obj, sub_obj, relationship, data, skip_sub_obj_read_check=skip_sub_obj_read_check)


class NotificationAttachMixin(BaseAccess):
    """For models that can have notifications attached

    I can attach a notification template when
    - I have notification_admin_role to organization of the NT
    - I can read the object I am attaching it to

    I can unattach when those same critiera are met
    """

    notification_attach_roles = None

    def _can_attach(self, notification_template, resource_obj):
        from forail.main.access.notifications import NotificationTemplateAccess

        if not NotificationTemplateAccess(self.user).can_change(notification_template, {}):
            return False
        if self.notification_attach_roles is None:
            return self.can_read(resource_obj)
        return any(self.user in getattr(resource_obj, role) for role in self.notification_attach_roles)

    @check_superuser
    def can_attach(self, obj, sub_obj, relationship, data, skip_sub_obj_read_check=False):
        if isinstance(sub_obj, NotificationTemplate):
            # reverse obj and sub_obj
            return self._can_attach(notification_template=sub_obj, resource_obj=obj)
        return super(NotificationAttachMixin, self).can_attach(obj, sub_obj, relationship, data, skip_sub_obj_read_check=skip_sub_obj_read_check)

    @check_superuser
    def can_unattach(self, obj, sub_obj, relationship, data=None):
        if isinstance(sub_obj, NotificationTemplate):
            # due to this special case, we use symmetrical logic with attach permission
            return self._can_attach(notification_template=sub_obj, resource_obj=obj)
        return super(NotificationAttachMixin, self).can_unattach(obj, sub_obj, relationship, data=data)
