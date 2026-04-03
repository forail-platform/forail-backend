from django.urls import re_path

from forge.api.views.eda import (
    EventRuleList,
    EventRuleDetail,
    EventRuleWebhookKey,
    EventRuleEventLogList,
    EventRuleTest,
    EventRuleToggle,
    EventLogList,
    EventLogDetail,
    OutboundWebhookList,
    OutboundWebhookDetail,
    OutboundWebhookTest,
    EDAWebhookReceiver,
)

event_rule_urls = [
    re_path(r'^$', EventRuleList.as_view(), name='event_rule_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', EventRuleDetail.as_view(), name='event_rule_detail'),
    re_path(r'^(?P<pk>[0-9]+)/webhook_key/$', EventRuleWebhookKey.as_view(), name='event_rule_webhook_key'),
    re_path(r'^(?P<pk>[0-9]+)/event_logs/$', EventRuleEventLogList.as_view(), name='event_rule_event_log_list'),
    re_path(r'^(?P<pk>[0-9]+)/test/$', EventRuleTest.as_view(), name='event_rule_test'),
    re_path(r'^(?P<pk>[0-9]+)/(?P<action>enable|disable)/$', EventRuleToggle.as_view(), name='event_rule_toggle'),
]

event_log_urls = [
    re_path(r'^$', EventLogList.as_view(), name='event_log_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', EventLogDetail.as_view(), name='event_log_detail'),
]

outbound_webhook_urls = [
    re_path(r'^$', OutboundWebhookList.as_view(), name='outbound_webhook_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', OutboundWebhookDetail.as_view(), name='outbound_webhook_detail'),
    re_path(r'^(?P<pk>[0-9]+)/test/$', OutboundWebhookTest.as_view(), name='outbound_webhook_test'),
]

eda_webhook_urls = [
    re_path(r'^(?P<webhook_path>[-\w]+)/$', EDAWebhookReceiver.as_view(), name='eda_webhook_receiver'),
]

__all__ = ['event_rule_urls', 'event_log_urls', 'outbound_webhook_urls', 'eda_webhook_urls']
