"""Access rules for the configuration objects Forail adds on top of AWX.

Event rules, outbound webhooks, drift alert rules, policies, scanners and
service catalog items all belong to an organization and change what the
platform does on that organization's behalf -- launch jobs, block launches,
send data to an outside URL. Until 2026-10 their API views only required an
authenticated user and filtered by organization membership, so any member
could edit them, and none had an access class, so DELETE failed with a
KeyError for everyone.

The rule here is the one AWX applies to notification templates: anyone in
the organization may read; changing, adding or deleting takes an admin of
that organization. Objects that reference something they will run --
an event rule's actions, a catalog item's template -- additionally require
that the user could run it themselves, so a rule cannot launch what its
author may not.
"""

from django.db.models import Q

from forail.main.access.base import BaseAccess, check_superuser
from forail.main.models import JobTemplate, NotificationTemplate, Organization, WorkflowJobTemplate
from forail.main.models.drift import DriftAlertRule
from forail.main.models.eda import EventRule, OutboundWebhook
from forail.main.models.policy import Policy
from forail.main.models.scanner import Scanner
from forail.main.models.service_catalog import ServiceCatalogItem


class OrganizationConfigAccess(BaseAccess):
    """Readable by the organization, managed by its admins."""

    model = None
    select_related = ('organization',)

    def filtered_queryset(self):
        # The visibility the views always had: the user's organizations, plus
        # objects with no organization, which only a superuser can create.
        orgs = Organization.accessible_pk_qs(self.user, 'read_role')
        return self.model.objects.filter(Q(organization__in=orgs) | Q(organization__isnull=True))

    def _is_org_admin(self, organization):
        return organization is not None and self.user in organization.admin_role

    @check_superuser
    def can_add(self, data):
        if not data:
            # Asked by the OPTIONS / list views: could this user create one anywhere?
            return Organization.accessible_objects(self.user, 'admin_role').exists()
        return self.check_related('organization', Organization, data, role_field='admin_role', mandatory=True) and self.can_use_targets(data)

    @check_superuser
    def can_change(self, obj, data):
        if not self._is_org_admin(obj.organization):
            return False
        return self.check_related('organization', Organization, data, obj=obj, role_field='admin_role') and self.can_use_targets(data, obj)

    def can_delete(self, obj):
        return self.can_change(obj, None)

    def can_use_targets(self, data, obj=None):
        """Hook: may the user point this object at what ``data`` references?"""
        return True


class EventRuleAccess(OrganizationConfigAccess):
    model = EventRule

    # action_type -> (model, the access method the rule's author must pass)
    ACTION_TARGETS = {
        'launch_job_template': (JobTemplate, 'start'),
        'launch_workflow': (WorkflowJobTemplate, 'start'),
        'send_notification': (NotificationTemplate, 'read'),
    }

    def can_use_targets(self, data, obj=None):
        # A rule fires from an unauthenticated webhook and launches as the
        # system. Without this, anyone allowed to edit a rule could aim it at
        # any template in any organization.
        actions = (data or {}).get('actions')
        if not actions or not isinstance(actions, list):
            return True
        for action in actions:
            if not isinstance(action, dict):
                continue  # the serializer rejects it with a proper message
            target = self.ACTION_TARGETS.get(action.get('action_type'))
            if target is None or not action.get('target_id'):
                continue
            Model, method = target
            instance = Model.objects.filter(pk=action['target_id']).first()
            if instance is None:
                return False
            if method == 'start':
                allowed = self.user.can_access(Model, method, instance, validate_license=False)
            else:
                allowed = self.user.can_access(Model, method, instance)
            if not allowed:
                return False
        return True


class OutboundWebhookAccess(OrganizationConfigAccess):
    model = OutboundWebhook


class DriftAlertRuleAccess(OrganizationConfigAccess):
    model = DriftAlertRule


class PolicyAccess(OrganizationConfigAccess):
    model = Policy


class ScannerAccess(OrganizationConfigAccess):
    model = Scanner


class ServiceCatalogItemAccess(OrganizationConfigAccess):
    model = ServiceCatalogItem

    def can_use_targets(self, data, obj=None):
        # A catalog item launches its template for requesters who need no
        # access to it -- that is the point of self-service. So whoever
        # publishes the item must be able to run the template themselves.
        return self.check_related('job_template', JobTemplate, data, obj=obj, role_field='execute_role') and self.check_related(
            'workflow_job_template', WorkflowJobTemplate, data, obj=obj, role_field='execute_role'
        )
