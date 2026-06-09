# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

import dateutil

from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

import pytz

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from forail.api.generics import (
    APIView,
    GenericAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    SubListAPIView,
    SubListAttachDetachAPIView,
)
from forail.api.views.labels import LabelSubListCreateAttachDetachView
from forail.api import serializers
from forail.main import models


class ScheduleList(ListCreateAPIView):
    name = _("Schedules")
    model = models.Schedule
    serializer_class = serializers.ScheduleSerializer
    ordering = ('id',)


class ScheduleDetail(RetrieveUpdateDestroyAPIView):
    model = models.Schedule
    serializer_class = serializers.ScheduleSerializer


class SchedulePreview(GenericAPIView):
    model = models.Schedule
    name = _('Schedule Recurrence Rule Preview')
    serializer_class = serializers.SchedulePreviewSerializer
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            next_stamp = now()
            schedule = []
            gen = models.Schedule.rrulestr(serializer.validated_data['rrule']).xafter(next_stamp, count=20)

            # loop across the entire generator and grab the first 10 events
            for event in gen:
                if len(schedule) >= 10:
                    break
                if not dateutil.tz.datetime_exists(event):
                    # skip imaginary dates, like 2:30 on DST boundaries
                    continue
                schedule.append(event)

            return Response({'local': schedule, 'utc': [s.astimezone(pytz.utc) for s in schedule]})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ScheduleZoneInfo(APIView):
    swagger_topic = 'System Configuration'

    def get(self, request):
        return Response({'zones': models.Schedule.get_zoneinfo(), 'links': models.Schedule.get_zoneinfo_links()})


class LaunchConfigCredentialsBase(SubListAttachDetachAPIView):
    model = models.Credential
    serializer_class = serializers.CredentialSerializer
    relationship = 'credentials'

    def is_valid_relation(self, parent, sub, created=False):
        if not parent.unified_job_template:
            return {"msg": _("Cannot assign credential when related template is null.")}

        ask_mapping = parent.unified_job_template.get_ask_mapping()

        if self.relationship not in ask_mapping:
            return {"msg": _("Related template cannot accept {} on launch.").format(self.relationship)}
        elif sub.passwords_needed:
            return {"msg": _("Credential that requires user input on launch cannot be used in saved launch configuration.")}

        ask_field_name = ask_mapping[self.relationship]

        if not getattr(parent.unified_job_template, ask_field_name):
            return {"msg": _("Related template is not configured to accept credentials on launch.")}
        elif sub.unique_hash() in [cred.unique_hash() for cred in parent.credentials.all()]:
            return {
                "msg": _("This launch configuration already provides a {credential_type} credential.").format(credential_type=sub.unique_hash(display=True))
            }
        elif sub.pk in parent.unified_job_template.credentials.values_list('pk', flat=True):
            return {"msg": _("Related template already uses {credential_type} credential.").format(credential_type=sub.name)}

        # None means there were no validation errors
        return None


class ScheduleCredentialsList(LaunchConfigCredentialsBase):
    parent_model = models.Schedule


class ScheduleLabelsList(LabelSubListCreateAttachDetachView):
    parent_model = models.Schedule


class ScheduleInstanceGroupList(SubListAttachDetachAPIView):
    model = models.InstanceGroup
    serializer_class = serializers.InstanceGroupSerializer
    parent_model = models.Schedule
    relationship = 'instance_groups'


class ScheduleUnifiedJobsList(SubListAPIView):
    model = models.UnifiedJob
    serializer_class = serializers.UnifiedJobListSerializer
    parent_model = models.Schedule
    relationship = 'unifiedjob_set'
    name = _('Schedule Jobs List')
