"""Policy-as-Code API views."""

import logging

from django.conf import settings as django_settings

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from forge.api.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    ListAPIView,
    RetrieveAPIView,
    APIView,
)
from forge.api.serializers.policy import (
    PolicySerializer,
    PolicyListSerializer,
    PolicyDecisionSerializer,
    PolicyDecisionListSerializer,
    PolicyTestSerializer,
)
from forge.main.models.policy import Policy, PolicyDecision

logger = logging.getLogger('forge.api.views.policy')


def _org_filtered(qs, user, org_field='organization_id'):
    if user.is_superuser or getattr(user, 'is_system_auditor', False):
        return qs
    user_org_ids = user.organizations.values_list('id', flat=True)
    from django.db.models import Q
    return qs.filter(Q(**{f'{org_field}__in': user_org_ids}) | Q(**{f'{org_field}__isnull': True}))


class PolicyList(ListCreateAPIView):
    model = Policy
    permission_classes = [IsAuthenticated]
    ordering = ('name',)

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return PolicyListSerializer
        return PolicySerializer

    def get_queryset(self):
        qs = Policy.objects.all()
        qs = _org_filtered(qs, self.request.user)
        params = self.request.query_params
        if params.get('enabled') is not None:
            v = params['enabled'].lower()
            if v in ('true', '1'):
                qs = qs.filter(enabled=True)
            elif v in ('false', '0'):
                qs = qs.filter(enabled=False)
        if params.get('search'):
            qs = qs.filter(name__icontains=params['search'])
        if params.get('organization'):
            qs = qs.filter(organization_id=params['organization'])
        if params.get('applies_to'):
            qs = qs.filter(applies_to__contains=[params['applies_to']])
        return qs


class PolicyDetail(RetrieveUpdateDestroyAPIView):
    model = Policy
    serializer_class = PolicySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _org_filtered(Policy.objects.all(), self.request.user)


class PolicyToggle(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        action = self.kwargs.get('action')
        try:
            policy = _org_filtered(Policy.objects.all(), request.user).get(pk=self.kwargs['pk'])
        except Policy.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        policy.enabled = (action == 'enable')
        policy.save(update_fields=['enabled', 'modified'])
        return Response({'enabled': policy.enabled})


class PolicyTest(APIView):
    """Dry-run a policy against a user-supplied input document."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            policy = _org_filtered(Policy.objects.all(), request.user).get(pk=self.kwargs['pk'])
        except Policy.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        ser = PolicyTestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        input_doc = ser.validated_data['input']

        from forge.main.policy.opa_client import evaluate as opa_evaluate, parse_decision, OPAUnavailable
        server_url = getattr(django_settings, 'OPA_SERVER_URL', '')
        timeout_ms = int(getattr(django_settings, 'OPA_EVALUATION_TIMEOUT_MS', 2000))
        try:
            result = opa_evaluate(server_url, policy.package_path, input_doc, timeout_ms)
        except OPAUnavailable as e:
            return Response({'error': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        warns, denies = parse_decision(result)
        return Response({
            'allowed': len(denies) == 0,
            'warnings': warns,
            'denies': denies,
            'raw': result,
        })


class PolicyDecisionList(ListAPIView):
    model = PolicyDecision
    permission_classes = [IsAuthenticated]
    ordering = ('-created',)

    def get_serializer_class(self):
        return PolicyDecisionListSerializer

    def get_queryset(self):
        qs = PolicyDecision.objects.select_related('policy', 'unified_job', 'triggered_by').all()
        qs = _org_filtered(qs, self.request.user)
        params = self.request.query_params
        if params.get('decision'):
            qs = qs.filter(decision=params['decision'])
        if params.get('policy'):
            qs = qs.filter(policy_id=params['policy'])
        if params.get('unified_job'):
            qs = qs.filter(unified_job_id=params['unified_job'])
        if params.get('since'):
            qs = qs.filter(created__gte=params['since'])
        return qs


class PolicyDecisionDetail(RetrieveAPIView):
    model = PolicyDecision
    serializer_class = PolicyDecisionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _org_filtered(PolicyDecision.objects.all(), self.request.user)
