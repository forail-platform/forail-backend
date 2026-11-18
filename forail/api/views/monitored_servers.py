"""Monitored servers (forail-mobile#52).

``/api/v2/monitored_servers/`` is filtered by RBAC like every other resource,
and anything a user may not read is a ``404`` -- in the list, on the detail and
on every sub-resource -- so the API never confirms that a server exists.

``/api/v2/monitored_servers/service/...`` is for the Forail Mobile backend only.
It takes the service token, never a user's credentials, and answers on behalf
of a user the mobile backend names.
"""

import json
import logging
import shlex

from ansible_base.rbac.models import RoleTeamAssignment, RoleUserAssignment
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from forail.api.generics import (
    APIView,
    GenericAPIView,
    ListCreateAPIView,
    ResourceAccessList,
    RetrieveUpdateDestroyAPIView,
    SubListAPIView,
)
from forail.api.serializers import ActivityStreamSerializer, RoleSerializer
from forail.api.serializers.monitored_servers import (
    EnrollmentCodeSerializer,
    MonitoredServerSerializer,
)
from forail.main.access.monitored_servers import (
    MonitoredServerAccess,
    internal_role_changes,
)
from forail.main.models import ActivityStream, Organization, Role
from forail.main.models.monitored_server import MonitoredServer
from forail.main.services import forail_mobile
from forail.main.signals import get_current_user_or_none

logger = logging.getLogger('forail.api.views.monitored_servers')


class MobileUnavailableError(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = _('Forail Mobile is not available. Try again later, or ask an administrator to check FORAIL_MOBILE_URL.')
    default_code = 'mobile_unavailable'


class ConflictError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'conflict'


def _client():
    return forail_mobile.ForailMobileClient()


def _statuses():
    """Online state from the mobile backend, or None when it cannot be asked."""
    if not forail_mobile.enabled():
        return None
    try:
        return _client().statuses()
    except forail_mobile.MobileUnavailable:
        return None


def record_activity(server, changes):
    """An activity stream entry for something that is not a field change."""
    if not settings.ACTIVITY_STREAM_ENABLED:
        return
    entry = ActivityStream(operation='update', object1='monitored_server', changes=json.dumps(changes), actor=get_current_user_or_none())
    entry.save()
    entry.monitored_server.add(server)


def install_command(code):
    api = forail_mobile.public_api_url()
    return f'sudo forail-agent enroll --api {shlex.quote(api)} --code {shlex.quote(code)}'


def enrollment_response(code, status_code):
    data = {
        'code': code.code,
        'expires_at': code.expires_at,
        'api_url': forail_mobile.public_api_url(),
        'command': install_command(code.code),
    }
    return Response(EnrollmentCodeSerializer(data).data, status=status_code)


class ReadableObjectMixin:
    """Look the server up among those the user may read: anything else is a 404."""

    def get_readable_server(self, pk):
        return get_object_or_404(self.request.user.get_queryset(MonitoredServer), pk=pk)


class MonitoredServerList(ListCreateAPIView):
    model = MonitoredServer
    serializer_class = MonitoredServerSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method == 'GET':
            context['mobile_statuses'] = _statuses()
        return context

    def create(self, request, *args, **kwargs):
        if not forail_mobile.enabled():
            raise MobileUnavailableError()
        user = request.user
        if not user.is_superuser:
            owned = MonitoredServer.objects.filter(owner=user).count()
            if owned >= settings.MONITORED_SERVERS_PER_USER:
                raise ConflictError(
                    _('You already own %(count)d monitored servers, the most one user may register.') % {'count': settings.MONITORED_SERVERS_PER_USER}
                )
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        user = self.request.user
        organization = serializer.validated_data['organization']
        name = serializer.validated_data['name']
        client = _client()
        try:
            mobile_id = client.create_server(name, organization.pk, user.pk)
        except forail_mobile.MobileConflict:
            raise ConflictError(_('Forail Mobile already has a server named %(name)s in this organization.') % {'name': name})
        except forail_mobile.MobileUnavailable:
            raise MobileUnavailableError()
        try:
            with transaction.atomic():
                server = serializer.save(owner=user, mobile_server_id=mobile_id)
                with internal_role_changes():
                    server.admin_role.members.add(user)
        except Exception:
            # Do not leave a server in the mobile backend that nobody here can see.
            try:
                client.delete_server(mobile_id)
            except forail_mobile.MobileUnavailable:
                logger.error('Monitored server %s was created in Forail Mobile but not saved here, and could not be removed there.', mobile_id)
            raise


class MonitoredServerDetail(ReadableObjectMixin, RetrieveUpdateDestroyAPIView):
    model = MonitoredServer
    serializer_class = MonitoredServerSerializer

    def get_queryset(self):
        return self.request.user.get_queryset(MonitoredServer)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method == 'GET':
            context['mobile_statuses'] = _statuses()
        return context

    def perform_destroy(self, instance):
        try:
            _client().delete_server(instance.mobile_server_id)
        except forail_mobile.MobileUnavailable:
            # The agent would keep reporting into a server nobody here can
            # see or delete any more; better to refuse and let them retry.
            raise MobileUnavailableError()
        with internal_role_changes():
            instance.delete()


class _EnrollmentAction(ReadableObjectMixin, GenericAPIView):
    model = MonitoredServer
    serializer_class = EnrollmentCodeSerializer
    activity = None

    def call_mobile(self, client, server):
        raise NotImplementedError

    def post(self, request, pk):
        server = self.get_readable_server(pk)
        if not MonitoredServerAccess(request.user).can_rotate(server):
            raise PermissionDenied()
        try:
            code = self.call_mobile(_client(), server)
        except forail_mobile.MobileNotFound:
            raise Http404
        except forail_mobile.MobileUnavailable:
            raise MobileUnavailableError()
        record_activity(server, self.activity)
        return enrollment_response(code, status.HTTP_201_CREATED)


class MonitoredServerEnrollmentCode(_EnrollmentAction):
    """Issue a one-time code (10 minutes, single use) for ``forail-agent enroll``."""

    activity = {'enrollment_code': 'issued'}

    def call_mobile(self, client, server):
        return client.enrollment_code(server.mobile_server_id, issued_by=self.request.user.pk)


class MonitoredServerRotateToken(_EnrollmentAction):
    """Revoke the agent's token. The agent stops reporting until the host re-enrolls with the code returned."""

    activity = {'agent_token': 'rotated'}

    def call_mobile(self, client, server):
        return client.rotate(server.mobile_server_id, issued_by=self.request.user.pk)


class _ReadableParentMixin:
    def get_parent_object(self):
        if self.parent_object is None:
            self.parent_object = get_object_or_404(self.request.user.get_queryset(MonitoredServer), pk=self.kwargs['pk'])
        return self.parent_object


class MonitoredServerAccessList(_ReadableParentMixin, ResourceAccessList):
    model = User
    parent_model = MonitoredServer


class MonitoredServerObjectRolesList(_ReadableParentMixin, SubListAPIView):
    model = Role
    serializer_class = RoleSerializer
    parent_model = MonitoredServer
    search_fields = ('role_field', 'content_type__model')

    def get_queryset(self):
        parent = self.get_parent_object()
        content_type = ContentType.objects.get_for_model(MonitoredServer)
        return Role.objects.filter(content_type=content_type, object_id=parent.pk)


class MonitoredServerActivityStreamList(_ReadableParentMixin, SubListAPIView):
    model = ActivityStream
    serializer_class = ActivityStreamSerializer
    parent_model = MonitoredServer
    relationship = 'activitystream_set'
    search_fields = ('changes',)


# --- for the Forail Mobile backend -----------------------------------------------


class _ServiceView(APIView):
    """Authenticated by the service token alone. A user's session or token is refused."""

    authentication_classes = []
    permission_classes = [AllowAny]
    exclude_from_schema = True

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not settings.FORAIL_MOBILE_SERVICE_TOKEN:
            raise Http404
        if not forail_mobile.service_token_matches(request.META.get('HTTP_AUTHORIZATION', '')):
            raise PermissionDenied(_('A Forail Mobile service token is required.'))

    def user_from_query(self):
        user_id = self.request.query_params.get('user', '')
        if not user_id.isdigit():
            raise Http404
        user = User.objects.filter(pk=int(user_id), is_active=True).first()
        if user is None:
            raise Http404
        return user


class MonitoredServerServiceVisible(_ServiceView):
    """The servers a user may read, by their Forail Mobile id.

    ``GET ?user=<platform user id>`` -> ``{"user": .., "results": [{"mobile_server_id", "role"}]}``.
    ``role`` is ``admin`` (may rotate, enroll, delete) or ``read``.
    """

    def get(self, request):
        user = self.user_from_query()
        access = MonitoredServerAccess(user)
        results = []
        for server in access.get_queryset().select_related('organization'):
            results.append({'mobile_server_id': str(server.mobile_server_id), 'role': 'admin' if access.can_rotate(server) else 'read'})
        return Response({'user': user.pk, 'results': results})


class MonitoredServerServiceAccess(_ServiceView):
    """Who has access to one server, and why. Read-only; shown in the mobile app.

    ``GET ?server=<mobile server id>`` -> ``{"results": [{"username", "role", "source"}]}``
    with ``source`` one of ``owner``, ``org_admin``, ``superuser``, ``granted``,
    ``team`` or ``org_auditor``.
    """

    def get(self, request):
        server = MonitoredServer.objects.filter(mobile_server_id=request.query_params.get('server') or None).select_related('organization', 'owner').first()
        if server is None:
            raise Http404
        return Response({'server': str(server.mobile_server_id), 'name': server.name, 'organization': server.organization.name, 'results': access_entries(server)})


def access_entries(server):
    """Every user who can read ``server``, with the strongest reason they can."""
    entries = {}
    rank = {'superuser': 0, 'owner': 1, 'org_admin': 2, 'granted': 3, 'team': 4, 'org_auditor': 5}

    def add(user, role, source, team=None):
        if not user.is_active:
            return
        entry = {'username': user.username, 'role': role, 'source': source}
        if team:
            entry['team'] = team
        current = entries.get(user.pk)
        if current is None or rank[source] < rank[current['source']]:
            entries[user.pk] = entry

    for user in User.objects.filter(is_superuser=True):
        add(user, 'admin', 'superuser')
    if server.owner_id:
        add(server.owner, 'admin', 'owner')

    server_ct = ContentType.objects.get_for_model(MonitoredServer)
    org_ct = ContentType.objects.get_for_model(Organization)

    def role_of(role_definition):
        codenames = set(role_definition.permissions.values_list('codename', flat=True))
        return 'admin' if 'change_monitoredserver' in codenames else 'read'

    def reaches_servers(role_definition):
        return role_definition.permissions.filter(codename='view_monitoredserver').exists()

    for assignment in RoleUserAssignment.objects.filter(content_type=server_ct, object_id=str(server.pk)).select_related('user', 'role_definition'):
        add(assignment.user, role_of(assignment.role_definition), 'granted')
    for assignment in RoleTeamAssignment.objects.filter(content_type=server_ct, object_id=str(server.pk)).select_related('team', 'role_definition'):
        for user in assignment.team.member_role.members.all():
            add(user, role_of(assignment.role_definition), 'team', team=assignment.team.name)
    for assignment in RoleUserAssignment.objects.filter(content_type=org_ct, object_id=str(server.organization_id)).select_related('user', 'role_definition'):
        rd = assignment.role_definition
        if not reaches_servers(rd):
            continue
        role = role_of(rd)
        add(assignment.user, role, 'org_admin' if role == 'admin' else 'org_auditor')

    return sorted(entries.values(), key=lambda e: (rank[e['source']], e['username']))


__all__ = [
    'MonitoredServerAccessList',
    'MonitoredServerActivityStreamList',
    'MonitoredServerDetail',
    'MonitoredServerEnrollmentCode',
    'MonitoredServerList',
    'MonitoredServerObjectRolesList',
    'MonitoredServerRotateToken',
    'MonitoredServerServiceAccess',
    'MonitoredServerServiceVisible',
]
