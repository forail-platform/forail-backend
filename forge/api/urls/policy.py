from django.urls import re_path

from forge.api.views.policy import (
    PolicyList,
    PolicyDetail,
    PolicyToggle,
    PolicyTest,
    PolicyDecisionList,
    PolicyDecisionDetail,
)

policy_urls = [
    re_path(r'^$', PolicyList.as_view(), name='policy_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', PolicyDetail.as_view(), name='policy_detail'),
    re_path(r'^(?P<pk>[0-9]+)/(?P<action>enable|disable)/$', PolicyToggle.as_view(), name='policy_toggle'),
    re_path(r'^(?P<pk>[0-9]+)/test/$', PolicyTest.as_view(), name='policy_test'),
]

policy_decision_urls = [
    re_path(r'^$', PolicyDecisionList.as_view(), name='policy_decision_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', PolicyDecisionDetail.as_view(), name='policy_decision_detail'),
]

__all__ = ['policy_urls', 'policy_decision_urls']
