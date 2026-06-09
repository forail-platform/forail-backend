# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from forail.api.generics import RetrieveAPIView, SimpleListAPIView
from forail.api import serializers
from forail.main import models


class ActivityStreamList(SimpleListAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
    search_fields = ('changes',)


class ActivityStreamDetail(RetrieveAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
