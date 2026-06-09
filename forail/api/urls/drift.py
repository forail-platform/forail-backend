from django.urls import re_path

from forail.api.views.drift import (
    HostFactSnapshotList,
    HostFactSnapshotDetail,
    DriftDetectionList,
    DriftDetectionDetail,
    DriftDetectionAcknowledge,
    DriftAlertRuleList,
    DriftAlertRuleDetail,
    DriftAlertRuleToggle,
    DriftAlertList,
    DriftAlertDetail,
    DriftSummaryView,
    DriftCompareView,
    DriftExportView,
    HostDriftHistory,
)

fact_snapshot_urls = [
    re_path(r'^$', HostFactSnapshotList.as_view(), name='fact_snapshot_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', HostFactSnapshotDetail.as_view(), name='fact_snapshot_detail'),
]

drift_detection_urls = [
    re_path(r'^$', DriftDetectionList.as_view(), name='drift_detection_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', DriftDetectionDetail.as_view(), name='drift_detection_detail'),
    re_path(r'^(?P<pk>[0-9]+)/acknowledge/$', DriftDetectionAcknowledge.as_view(), name='drift_detection_acknowledge'),
    re_path(r'^compare/$', DriftCompareView.as_view(), name='drift_compare'),
    re_path(r'^export/$', DriftExportView.as_view(), name='drift_export'),
    re_path(r'^summary/$', DriftSummaryView.as_view(), name='drift_summary'),
]

drift_alert_rule_urls = [
    re_path(r'^$', DriftAlertRuleList.as_view(), name='drift_alert_rule_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', DriftAlertRuleDetail.as_view(), name='drift_alert_rule_detail'),
    re_path(r'^(?P<pk>[0-9]+)/(?P<action>enable|disable)/$', DriftAlertRuleToggle.as_view(), name='drift_alert_rule_toggle'),
]

drift_alert_urls = [
    re_path(r'^$', DriftAlertList.as_view(), name='drift_alert_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', DriftAlertDetail.as_view(), name='drift_alert_detail'),
]

__all__ = ['fact_snapshot_urls', 'drift_detection_urls', 'drift_alert_rule_urls', 'drift_alert_urls']
