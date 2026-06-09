# Copyright (c) 2017 Ansible, Inc.
# All Rights Reserved.

from django.urls import re_path

from forail.api.views import JobHostSummaryDetail


urls = [re_path(r'^(?P<pk>[0-9]+)/$', JobHostSummaryDetail.as_view(), name='job_host_summary_detail')]

__all__ = ['urls']
