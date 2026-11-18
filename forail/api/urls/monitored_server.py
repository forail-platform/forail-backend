from django.urls import re_path

from forail.api.views.monitored_servers import (
    MonitoredServerAccessList,
    MonitoredServerActivityStreamList,
    MonitoredServerDetail,
    MonitoredServerEnrollmentCode,
    MonitoredServerList,
    MonitoredServerObjectRolesList,
    MonitoredServerRotateToken,
    MonitoredServerServiceAccess,
    MonitoredServerServiceVisible,
)

urls = [
    re_path(r'^$', MonitoredServerList.as_view(), name='monitored_server_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', MonitoredServerDetail.as_view(), name='monitored_server_detail'),
    re_path(r'^(?P<pk>[0-9]+)/enrollment_code/$', MonitoredServerEnrollmentCode.as_view(), name='monitored_server_enrollment_code'),
    re_path(r'^(?P<pk>[0-9]+)/rotate_token/$', MonitoredServerRotateToken.as_view(), name='monitored_server_rotate_token'),
    re_path(r'^(?P<pk>[0-9]+)/access_list/$', MonitoredServerAccessList.as_view(), name='monitored_server_access_list'),
    re_path(r'^(?P<pk>[0-9]+)/object_roles/$', MonitoredServerObjectRolesList.as_view(), name='monitored_server_object_roles_list'),
    re_path(r'^(?P<pk>[0-9]+)/activity_stream/$', MonitoredServerActivityStreamList.as_view(), name='monitored_server_activity_stream_list'),
    # For the Forail Mobile backend, with the service token.
    re_path(r'^service/visible/$', MonitoredServerServiceVisible.as_view(), name='monitored_server_service_visible'),
    re_path(r'^service/access/$', MonitoredServerServiceAccess.as_view(), name='monitored_server_service_access'),
]

__all__ = ['urls']
