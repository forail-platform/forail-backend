"""Monitored servers: hosts that run ``forail-agent`` and report to Forail Mobile.

The platform is the source of truth for *which* servers exist and *who* may
reach them. Telemetry, logs and the agent's token live in the Forail Mobile
backend; this model only keeps the link (``mobile_server_id``) and the RBAC.

Who may do what (forail-mobile#52):

* the owner -- the user who registered the server -- sees it, rotates its
  agent token, issues enrollment codes and deletes it, but cannot share it;
* admins of the server's organization and superusers can do all of that and
  grant or revoke access;
* users granted ``read_role`` see the server; everyone else gets ``404``.
"""

import re

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from forail.api.versioning import reverse
from forail.main.fields import ImplicitRoleField
from forail.main.models.base import CommonModelNameNotUnique
from forail.main.models.mixins import ResourceMixin
from forail.main.models.rbac import (
    ROLE_SINGLETON_SYSTEM_ADMINISTRATOR,
    ROLE_SINGLETON_SYSTEM_AUDITOR,
)

__all__ = ['SERVER_NAME', 'MonitoredServer']

# The name travels into signed approval payloads on the phone, so it follows
# the rule the Forail Mobile backend enforces (shared/ApprovalPayload.SERVER_NAME).
SERVER_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$')


def validate_server_name(value):
    if not SERVER_NAME.match(value or ''):
        raise ValidationError(_('Use 1-63 letters, digits, dots, dashes or underscores, starting with a letter or digit.'))


class MonitoredServer(CommonModelNameNotUnique, ResourceMixin):
    class Meta:
        app_label = 'main'
        ordering = ('organization__name', 'name')
        unique_together = [('organization', 'name')]

    name = models.CharField(max_length=63, validators=[validate_server_name])
    organization = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='monitored_servers',
        help_text=_('The organization whose admins manage this server.'),
    )
    owner = models.ForeignKey(
        'auth.User',
        null=True,
        on_delete=models.SET_NULL,
        related_name='owned_monitored_servers',
        help_text=_('The user who registered the server.'),
    )
    mobile_server_id = models.UUIDField(
        unique=True,
        editable=False,
        help_text=_('The id of this server in the Forail Mobile backend.'),
    )

    admin_role = ImplicitRoleField(
        parent_role=[
            'singleton:' + ROLE_SINGLETON_SYSTEM_ADMINISTRATOR,
            'organization.admin_role',
        ],
    )
    read_role = ImplicitRoleField(
        parent_role=[
            'singleton:' + ROLE_SINGLETON_SYSTEM_AUDITOR,
            'organization.auditor_role',
            'admin_role',
        ],
    )

    def get_absolute_url(self, request=None):
        return reverse('api:monitored_server_detail', kwargs={'pk': self.pk}, request=request)

    def __str__(self):
        return self.name
