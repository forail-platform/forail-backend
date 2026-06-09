# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework import status

from forail.api.generics import (
    ListAPIView,
    RetrieveAPIView,
    RetrieveDestroyAPIView,
    RetrieveUpdateDestroyAPIView,
    SubListAPIView,
)
from forail.api.views.mixin import RelatedJobsPreventDeleteMixin, UnifiedJobDeletionMixin
from forail.api.permissions import WorkflowApprovalPermission
from forail.api import serializers
from forail.main import models


class WorkflowApprovalTemplateDetail(RelatedJobsPreventDeleteMixin, RetrieveUpdateDestroyAPIView):
    model = models.WorkflowApprovalTemplate
    serializer_class = serializers.WorkflowApprovalTemplateSerializer


class WorkflowApprovalTemplateJobsList(SubListAPIView):
    model = models.WorkflowApproval
    serializer_class = serializers.WorkflowApprovalListSerializer
    parent_model = models.WorkflowApprovalTemplate
    relationship = 'approvals'
    parent_key = 'workflow_approval_template'


class WorkflowApprovalList(ListAPIView):
    model = models.WorkflowApproval
    serializer_class = serializers.WorkflowApprovalListSerializer

    def get(self, request, *args, **kwargs):
        return super(WorkflowApprovalList, self).get(request, *args, **kwargs)


class WorkflowApprovalDetail(UnifiedJobDeletionMixin, RetrieveDestroyAPIView):
    model = models.WorkflowApproval
    serializer_class = serializers.WorkflowApprovalSerializer


class WorkflowApprovalApprove(RetrieveAPIView):
    model = models.WorkflowApproval
    serializer_class = serializers.WorkflowApprovalViewSerializer
    permission_classes = (WorkflowApprovalPermission,)

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        if not request.user.can_access(models.WorkflowApproval, 'approve_or_deny', obj):
            raise PermissionDenied(detail=_("User does not have permission to approve or deny this workflow."))
        if obj.status != 'pending':
            return Response({"error": _("This workflow step has already been approved or denied.")}, status=status.HTTP_400_BAD_REQUEST)
        obj.approve(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkflowApprovalDeny(RetrieveAPIView):
    model = models.WorkflowApproval
    serializer_class = serializers.WorkflowApprovalViewSerializer
    permission_classes = (WorkflowApprovalPermission,)

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        if not request.user.can_access(models.WorkflowApproval, 'approve_or_deny', obj):
            raise PermissionDenied(detail=_("User does not have permission to approve or deny this workflow."))
        if obj.status != 'pending':
            return Response({"error": _("This workflow step has already been approved or denied.")}, status=status.HTTP_400_BAD_REQUEST)
        obj.deny(request)
        return Response(status=status.HTTP_204_NO_CONTENT)
