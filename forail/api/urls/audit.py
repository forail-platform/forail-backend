from django.urls import re_path

from forail.api.views.audit import AuditEventList, AuditEventDetail

urls = [
    re_path(r'^$', AuditEventList.as_view(), name='audit_event_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', AuditEventDetail.as_view(), name='audit_event_detail'),
]

__all__ = ['urls']
