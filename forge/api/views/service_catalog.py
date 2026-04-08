"""Self-Service Portal API views."""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from forge.api.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    ListAPIView,
    APIView,
)
from forge.api.serializers.service_catalog import (
    ServiceCatalogItemSerializer,
    ServiceCatalogItemListSerializer,
    ServiceRequestSerializer,
    ServiceRequestListSerializer,
    ServiceRequestSubmitSerializer,
    ServiceRequestRejectSerializer,
)
from forge.main.models.service_catalog import ServiceCatalogItem, ServiceRequest

logger = logging.getLogger('forge.api.views.service_catalog')


def _org_filtered_qs(qs, user, org_field='organization_id'):
    if user.is_superuser or getattr(user, 'is_system_auditor', False):
        return qs
    user_org_ids = user.organizations.values_list('id', flat=True)
    return qs.filter(**{f'{org_field}__in': user_org_ids})


# ---------------------------------------------------------------------------
# ServiceCatalogItem (CRUD)
# ---------------------------------------------------------------------------

class ServiceCatalogItemList(ListCreateAPIView):
    model = ServiceCatalogItem
    permission_classes = [IsAuthenticated]
    ordering = ('category', 'name')

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return ServiceCatalogItemListSerializer
        return ServiceCatalogItemSerializer

    def get_queryset(self):
        qs = ServiceCatalogItem.objects.all()
        qs = _org_filtered_qs(qs, self.request.user)
        params = self.request.query_params
        if params.get('category'):
            qs = qs.filter(category=params['category'])
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
        return qs


class ServiceCatalogItemDetail(RetrieveUpdateDestroyAPIView):
    model = ServiceCatalogItem
    serializer_class = ServiceCatalogItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _org_filtered_qs(ServiceCatalogItem.objects.all(), self.request.user)


class ServiceCatalogItemLaunchData(APIView):
    """Return survey/launch metadata of the underlying JT or WFJT."""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        pk = self.kwargs['pk']
        qs = _org_filtered_qs(ServiceCatalogItem.objects.all(), request.user)
        try:
            item = qs.get(pk=pk)
        except ServiceCatalogItem.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        tpl = item.underlying_template
        if tpl is None:
            return Response({'detail': 'No underlying template.'}, status=400)

        data = {
            'catalog_item': {
                'id': item.id,
                'name': item.name,
                'description': item.description,
                'icon': item.icon,
                'requires_approval': item.requires_approval,
            },
            'is_workflow': item.is_workflow,
            'survey_enabled': bool(getattr(tpl, 'survey_enabled', False)),
            'survey_spec': getattr(tpl, 'survey_spec', {}) or {},
            'ask_variables_on_launch': bool(getattr(tpl, 'ask_variables_on_launch', False)),
        }

        if item.is_workflow:
            node_surveys = []
            try:
                for node in tpl.workflow_job_template_nodes.filter(survey_enabled=True):
                    node_surveys.append({
                        'node_id': node.id,
                        'identifier': node.identifier or str(node.id),
                        'survey_spec': node.survey_spec or {},
                    })
            except Exception:
                pass
            data['node_surveys'] = node_surveys

        return Response(data)


# ---------------------------------------------------------------------------
# ServiceRequest
# ---------------------------------------------------------------------------

class ServiceCatalogItemRequestsList(ListAPIView):
    """All requests for a single catalog item (admin view)."""
    model = ServiceRequest
    permission_classes = [IsAuthenticated]
    ordering = ('-created',)

    def get_serializer_class(self):
        return ServiceRequestListSerializer

    def get_queryset(self):
        item_pk = self.kwargs['pk']
        qs = ServiceRequest.objects.filter(catalog_item_id=item_pk).select_related(
            'catalog_item', 'requested_by', 'approved_by', 'unified_job',
        )
        if not (self.request.user.is_superuser or getattr(self.request.user, 'is_system_auditor', False)):
            qs = qs.filter(catalog_item__organization__in=self.request.user.organizations.all())
        return qs


class ServiceCatalogItemSubmit(APIView):
    """Submit a new ServiceRequest for a catalog item."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        pk = self.kwargs['pk']
        qs = _org_filtered_qs(ServiceCatalogItem.objects.all(), request.user)
        try:
            item = qs.get(pk=pk, enabled=True)
        except ServiceCatalogItem.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        ser = ServiceRequestSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        sr = ServiceRequest.objects.create(
            catalog_item=item,
            requested_by=request.user,
            extra_vars=data.get('extra_vars') or {},
            node_survey_data=data.get('node_survey_data') or {},
            justification=data.get('justification') or '',
        )
        try:
            sr.submit()
        except DjangoValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        out = ServiceRequestSerializer(sr, context={'request': request}).data
        return Response(out, status=status.HTTP_201_CREATED)


class ServiceRequestList(ListAPIView):
    model = ServiceRequest
    permission_classes = [IsAuthenticated]
    ordering = ('-created',)

    def get_serializer_class(self):
        return ServiceRequestListSerializer

    def get_queryset(self):
        user = self.request.user
        qs = ServiceRequest.objects.select_related(
            'catalog_item', 'requested_by', 'approved_by', 'unified_job',
        )
        params = self.request.query_params

        if params.get('mine') in ('1', 'true', 'True'):
            qs = qs.filter(requested_by=user)
        elif not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            user_org_ids = user.organizations.values_list('id', flat=True)
            qs = qs.filter(catalog_item__organization_id__in=user_org_ids)

        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('catalog_item'):
            qs = qs.filter(catalog_item_id=params['catalog_item'])
        return qs


class ServiceRequestDetail(APIView):
    permission_classes = [IsAuthenticated]

    def _get_obj(self, request, pk):
        try:
            sr = ServiceRequest.objects.select_related(
                'catalog_item', 'requested_by', 'approved_by', 'unified_job',
            ).get(pk=pk)
        except ServiceRequest.DoesNotExist:
            return None
        user = request.user
        if user.is_superuser or getattr(user, 'is_system_auditor', False):
            return sr
        if sr.requested_by_id == user.id:
            return sr
        org = sr.catalog_item.organization
        if org and user.organizations.filter(pk=org.pk).exists():
            return sr
        return None

    def get(self, request, *args, **kwargs):
        sr = self._get_obj(request, self.kwargs['pk'])
        if sr is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(ServiceRequestSerializer(sr, context={'request': request}).data)

    def delete(self, request, *args, **kwargs):
        sr = self._get_obj(request, self.kwargs['pk'])
        if sr is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if sr.status not in ('pending_approval', 'rejected'):
            return Response({'detail': 'Cannot delete a running or completed request.'}, status=400)
        sr.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServiceRequestApprove(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            sr = ServiceRequest.objects.select_related('catalog_item').get(pk=self.kwargs['pk'])
        except ServiceRequest.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            sr.approve(request.user)
        except DjangoValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ServiceRequestSerializer(sr, context={'request': request}).data)


class ServiceRequestReject(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            sr = ServiceRequest.objects.select_related('catalog_item').get(pk=self.kwargs['pk'])
        except ServiceRequest.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ser = ServiceRequestRejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            sr.reject(request.user, reason=ser.validated_data.get('reason') or '')
        except DjangoValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ServiceRequestSerializer(sr, context={'request': request}).data)


class ServiceRequestPendingApprovalsList(ListAPIView):
    """Approval inbox for the calling user."""
    model = ServiceRequest
    permission_classes = [IsAuthenticated]
    ordering = ('-created',)

    def get_serializer_class(self):
        return ServiceRequestListSerializer

    def get_queryset(self):
        user = self.request.user
        qs = ServiceRequest.objects.filter(status='pending_approval').select_related(
            'catalog_item', 'requested_by',
        )
        if user.is_superuser:
            return qs
        # Filter to those where the user can approve
        approvable_ids = []
        for sr in qs:
            if sr.can_user_approve(user):
                approvable_ids.append(sr.pk)
        return qs.filter(pk__in=approvable_ids)
