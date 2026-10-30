"""Access rules for monitored servers (forail-mobile#52).

=============================  ==========  ===============  ==============
Role                           See it      Rotate / delete  Grant / revoke
=============================  ==========  ===============  ==============
Owner (registered it)          yes         yes              no
Admin of its organization      yes         yes              yes
Superuser                      yes         yes              yes
Granted ``read_role``          yes         no               no
Anyone else                    404         --               --
=============================  ==========  ===============  ==============

The owner holds ``admin_role`` on their server so they can run it end to end,
but sharing it is an organization decision. Both ways of granting a role --
the old ``/roles/`` endpoints and django-ansible-base's role assignments --
end in :func:`check_can_manage_access`.
"""

import contextlib
import threading

from crum import get_current_user
from rest_framework.exceptions import PermissionDenied

from forail.main.access.base import BaseAccess, check_superuser
from forail.main.models import Organization
from forail.main.models.monitored_server import MonitoredServer


class MonitoredServerAccess(BaseAccess):
    model = MonitoredServer
    select_related = ('organization', 'owner', 'created_by', 'modified_by')
    prefetch_related = ('admin_role', 'read_role')

    def filtered_queryset(self):
        return self.model.accessible_objects(self.user, 'read_role')

    @check_superuser
    def can_add(self, data):
        # Any member of the organization may register their own server.
        if not data:
            return Organization.accessible_objects(self.user, 'member_role').exists()
        return self.check_related('organization', Organization, data, role_field='member_role', mandatory=True)

    @check_superuser
    def can_change(self, obj, data):
        if obj is None or self.user not in obj.admin_role:
            return False
        if data and 'organization' in data:
            # Moving a server hands it to other admins; only a superuser may.
            org_id = getattr(data['organization'], 'pk', data['organization'])
            return str(org_id) == str(obj.organization_id)
        return True

    def can_delete(self, obj):
        return self.can_change(obj, None)

    def can_rotate(self, obj):
        """Rotate the agent token or issue a new enrollment code."""
        return self.can_change(obj, None)

    @check_superuser
    def can_manage_access(self, obj):
        """Grant or revoke roles on the server: org admins and superusers only."""
        return obj is not None and self.user in obj.organization.admin_role

    def get_user_capabilities(self, obj, **kwargs):
        capabilities = super().get_user_capabilities(obj, **kwargs)
        capabilities['rotate'] = self.can_rotate(obj)
        capabilities['manage_access'] = self.can_manage_access(obj)
        return capabilities


# --- the grant guard -------------------------------------------------------------

_bypass = threading.local()


@contextlib.contextmanager
def internal_role_changes():
    """Role changes Forail makes itself: the owner's role on create, cleanup on delete."""
    previous = getattr(_bypass, 'active', False)
    _bypass.active = True
    try:
        yield
    finally:
        _bypass.active = previous


def check_can_manage_access(server, user=None):
    """Raise ``PermissionDenied`` unless ``user`` may grant or revoke on ``server``.

    Called for every role assignment on a monitored server, whichever API made
    it. A change with no user behind it (a management command, a migration)
    or made by Forail itself is allowed.
    """
    if getattr(_bypass, 'active', False):
        return
    user = user if user is not None else get_current_user()
    if user is None or not getattr(user, 'is_authenticated', False):
        return
    if not MonitoredServerAccess(user).can_manage_access(server):
        raise PermissionDenied('Access to a monitored server is granted by the admins of its organization.')
