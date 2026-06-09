"""EDA (Event-Driven Automation) API views."""

import logging
from hashlib import sha1

from django.utils.encoding import force_bytes
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from forail.api.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView, ListAPIView, RetrieveAPIView, APIView
from forail.api.serializers.eda import (
    EventRuleSerializer,
    EventRuleListSerializer,
    EventLogSerializer,
    EventLogListSerializer,
    OutboundWebhookSerializer,
)
from forail.main.models.eda import EventRule, EventLog, OutboundWebhook

logger = logging.getLogger('forail.api.views.eda')


# ---------------------------------------------------------------------------
# EventRule CRUD
# ---------------------------------------------------------------------------

class EventRuleList(ListCreateAPIView):
    model = EventRule
    permission_classes = [IsAuthenticated]
    ordering = ('name',)

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return EventRuleListSerializer
        return EventRuleSerializer

    def get_queryset(self):
        qs = EventRule.objects.all()
        user = self.request.user
        if not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            user_org_ids = user.organizations.values_list('id', flat=True)
            qs = qs.filter(organization_id__in=user_org_ids)

        params = self.request.query_params
        if params.get('organization'):
            qs = qs.filter(organization_id=params['organization'])
        if params.get('source_type'):
            qs = qs.filter(source_type=params['source_type'])
        if params.get('enabled') is not None:
            enabled_val = params['enabled'].lower()
            if enabled_val in ('true', '1'):
                qs = qs.filter(enabled=True)
            elif enabled_val in ('false', '0'):
                qs = qs.filter(enabled=False)
        if params.get('search'):
            qs = qs.filter(name__icontains=params['search'])
        return qs


class EventRuleDetail(RetrieveUpdateDestroyAPIView):
    model = EventRule
    serializer_class = EventRuleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = EventRule.objects.all()
        user = self.request.user
        if not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            user_org_ids = user.organizations.values_list('id', flat=True)
            qs = qs.filter(organization_id__in=user_org_ids)
        return qs


class EventRuleWebhookKey(APIView):
    """Get or rotate the webhook key for an EventRule."""
    permission_classes = [IsAuthenticated]

    def get_object(self):
        pk = self.kwargs['pk']
        try:
            obj = EventRule.objects.get(pk=pk)
        except EventRule.DoesNotExist:
            raise PermissionDenied
        user = self.request.user
        if not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            user_org_ids = user.organizations.values_list('id', flat=True)
            if obj.organization_id not in user_org_ids:
                raise PermissionDenied
        return obj

    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        return Response({'webhook_key': obj.webhook_key})

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        obj.rotate_webhook_key()
        obj.save(update_fields=['webhook_key'])
        return Response({'webhook_key': obj.webhook_key}, status=status.HTTP_201_CREATED)


class EventRuleEventLogList(ListAPIView):
    """List event logs for a specific rule."""
    serializer_class = EventLogListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        rule_pk = self.kwargs['pk']
        qs = EventLog.objects.filter(event_rule_id=rule_pk)
        user = self.request.user
        if not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            user_org_ids = user.organizations.values_list('id', flat=True)
            qs = qs.filter(organization_id__in=user_org_ids)
        return qs.order_by('-created')


class EventRuleTest(APIView):
    """Dry-run: evaluate conditions against a sample payload without firing actions."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        pk = self.kwargs['pk']
        try:
            rule = EventRule.objects.get(pk=pk)
        except EventRule.DoesNotExist:
            raise PermissionDenied

        payload = request.data.get('payload', {})
        headers = request.data.get('headers', {})

        from forail.main.tasks.eda import _evaluate_conditions
        matched, results = _evaluate_conditions(rule.conditions, payload, headers)

        return Response({
            'matched': matched,
            'condition_results': results,
            'would_fire': matched and not rule.is_throttled(),
            'actions': rule.actions,
        })


class EventRuleToggle(APIView):
    """Enable or disable an EventRule."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        pk = self.kwargs['pk']
        action = self.kwargs.get('action')

        try:
            rule = EventRule.objects.get(pk=pk)
        except EventRule.DoesNotExist:
            raise PermissionDenied

        user = self.request.user
        if not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            user_org_ids = user.organizations.values_list('id', flat=True)
            if rule.organization_id not in user_org_ids:
                raise PermissionDenied

        rule.enabled = (action == 'enable')
        rule.save(update_fields=['enabled'])

        return Response({'enabled': rule.enabled})


# ---------------------------------------------------------------------------
# EventLog (read-only)
# ---------------------------------------------------------------------------

class EventLogList(ListAPIView):
    model = EventLog
    permission_classes = [IsAuthenticated]
    ordering = ('-created',)

    def get_serializer_class(self):
        return EventLogListSerializer

    def get_queryset(self):
        qs = EventLog.objects.all()
        user = self.request.user
        if not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            user_org_ids = user.organizations.values_list('id', flat=True)
            qs = qs.filter(organization_id__in=user_org_ids)

        params = self.request.query_params
        if params.get('event_rule'):
            qs = qs.filter(event_rule_id=params['event_rule'])
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('source_type'):
            qs = qs.filter(source_type=params['source_type'])
        if params.get('created__gte'):
            qs = qs.filter(created__gte=params['created__gte'])
        if params.get('created__lte'):
            qs = qs.filter(created__lte=params['created__lte'])
        if params.get('search'):
            qs = qs.filter(event_rule_name__icontains=params['search'])
        return qs


class EventLogDetail(RetrieveAPIView):
    model = EventLog
    serializer_class = EventLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = EventLog.objects.all()
        user = self.request.user
        if not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            user_org_ids = user.organizations.values_list('id', flat=True)
            qs = qs.filter(organization_id__in=user_org_ids)
        return qs


# ---------------------------------------------------------------------------
# OutboundWebhook CRUD
# ---------------------------------------------------------------------------

class OutboundWebhookList(ListCreateAPIView):
    model = OutboundWebhook
    serializer_class = OutboundWebhookSerializer
    permission_classes = [IsAuthenticated]
    ordering = ('name',)

    def get_queryset(self):
        qs = OutboundWebhook.objects.all()
        user = self.request.user
        if not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            user_org_ids = user.organizations.values_list('id', flat=True)
            qs = qs.filter(organization_id__in=user_org_ids)

        params = self.request.query_params
        if params.get('organization'):
            qs = qs.filter(organization_id=params['organization'])
        if params.get('search'):
            qs = qs.filter(name__icontains=params['search'])
        return qs


class OutboundWebhookDetail(RetrieveUpdateDestroyAPIView):
    model = OutboundWebhook
    serializer_class = OutboundWebhookSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = OutboundWebhook.objects.all()
        user = self.request.user
        if not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            user_org_ids = user.organizations.values_list('id', flat=True)
            qs = qs.filter(organization_id__in=user_org_ids)
        return qs


class OutboundWebhookTest(APIView):
    """Send a test payload to the outbound webhook URL."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        pk = self.kwargs['pk']
        try:
            webhook = OutboundWebhook.objects.get(pk=pk)
        except OutboundWebhook.DoesNotExist:
            raise PermissionDenied

        from forail.main.tasks.eda import send_outbound_webhook

        test_data = {
            'event_type': 'test',
            'timestamp': str(__import__('django.utils.timezone', fromlist=['now']).now()),
            'job': {
                'id': 0,
                'name': 'Test Job',
                'status': 'successful',
                'type': 'Job',
            },
            'message': 'This is a test webhook from Forail EDA.',
        }

        send_outbound_webhook.delay(webhook.pk, test_data)

        return Response({'message': 'Test webhook queued for delivery.'})


# ---------------------------------------------------------------------------
# Public webhook receiver (no auth required)
# ---------------------------------------------------------------------------

class EDAWebhookReceiver(APIView):
    """
    Public endpoint that receives inbound webhooks and dispatches them
    to the EDA rule engine for evaluation.

    URL: /api/v2/eda_webhooks/<webhook_path>/
    Method: POST
    Auth: None (signature verified via HMAC)
    """
    permission_classes = (AllowAny,)
    authentication_classes = ()

    @csrf_exempt
    def post(self, request, *args, **kwargs):
        webhook_path = self.kwargs.get('webhook_path', '')

        # Look up the rule
        try:
            rule = EventRule.objects.select_related('organization').get(
                webhook_path=webhook_path,
                enabled=True,
            )
        except EventRule.DoesNotExist:
            raise PermissionDenied

        # Extract useful headers
        relevant_headers = {}
        for key in ('HTTP_X_HUB_SIGNATURE', 'HTTP_X_HUB_SIGNATURE_256',
                     'HTTP_X_GITLAB_TOKEN', 'HTTP_X_GITLAB_EVENT',
                     'HTTP_X_GITHUB_EVENT', 'HTTP_X_GITHUB_DELIVERY',
                     'HTTP_X_FORAIL_SIGNATURE', 'CONTENT_TYPE',
                     'HTTP_X_REQUEST_ID', 'HTTP_X_FORWARDED_FOR'):
            if key in request.META:
                # Convert Django META keys to standard header format
                header_name = key.replace('HTTP_', '').replace('_', '-').title()
                relevant_headers[header_name] = request.META[key]

        # Get source IP
        source_ip = (
            request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            or request.META.get('REMOTE_ADDR')
        )

        # Ensure body is read
        body = request.body

        # Verify signature
        try:
            rule.check_signature(body, relevant_headers)
        except ValueError as e:
            # Log the failed attempt
            EventLog.objects.create(
                event_rule=rule,
                source_ip=source_ip,
                payload=request.data if hasattr(request, 'data') else {},
                headers=relevant_headers,
                status='signature_failed',
                error_detail=str(e),
            )
            raise PermissionDenied

        # Extract event type and GUID based on source type
        event_type = self._extract_event_type(request, rule.source_type)
        event_guid = self._extract_event_guid(request, rule.source_type, body)

        # Deduplication check
        if event_guid and EventLog.objects.filter(
            event_rule=rule,
            event_guid=event_guid,
            status__in=['matched', 'action_fired'],
        ).exists():
            return Response(
                {'message': 'Event previously received.'},
                status=status.HTTP_202_ACCEPTED,
            )

        # Limit payload size (1MB)
        if len(body) > 1_048_576:
            return Response(
                {'error': 'Payload too large (max 1MB).'},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # Create event log
        event_log = EventLog.objects.create(
            event_rule=rule,
            source_ip=source_ip,
            event_type=event_type,
            event_guid=event_guid,
            payload=request.data if hasattr(request, 'data') else {},
            headers=relevant_headers,
            status='received',
        )

        # Dispatch to Celery for async evaluation
        from forail.main.tasks.eda import evaluate_event_rule
        evaluate_event_rule.delay(event_log.pk)

        return Response(
            {'message': 'Event received and queued for processing.'},
            status=status.HTTP_202_ACCEPTED,
        )

    def _extract_event_type(self, request, source_type):
        if source_type == 'webhook_github':
            return request.META.get('HTTP_X_GITHUB_EVENT', '')
        elif source_type == 'webhook_gitlab':
            return request.META.get('HTTP_X_GITLAB_EVENT', '')
        elif source_type == 'alertmanager':
            return request.data.get('status', 'alert') if hasattr(request, 'data') else ''
        elif source_type == 'pagerduty':
            messages = request.data.get('messages', []) if hasattr(request, 'data') else []
            if messages:
                return messages[0].get('event', '')
            return ''
        return request.data.get('event_type', '') if hasattr(request, 'data') else ''

    def _extract_event_guid(self, request, source_type, body):
        if source_type == 'webhook_github':
            return request.META.get('HTTP_X_GITHUB_DELIVERY', '')
        elif source_type == 'webhook_gitlab':
            # GitLab doesn't provide a GUID, generate from body hash
            h = sha1()
            h.update(force_bytes(body))
            return h.hexdigest()
        elif source_type in ('alertmanager', 'pagerduty', 'datadog', 'cloudwatch'):
            return request.META.get('HTTP_X_REQUEST_ID', '')
        return request.META.get('HTTP_X_REQUEST_ID', '') or request.data.get('event_id', '') if hasattr(request, 'data') else ''
