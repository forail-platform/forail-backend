from django.urls import re_path

from forge.api.views.forge_analytics import (
    ForgeAnalyticsRootView,
    JobTrendsView,
    SuccessRateView,
    TopTemplatesView,
    BusiestHostsView,
    HostCoverageView,
    FailureAnalysisView,
    TimeSavingsView,
)

urls = [
    re_path(r'^$', ForgeAnalyticsRootView.as_view(), name='forge_analytics_root'),
    re_path(r'^job_trends/$', JobTrendsView.as_view(), name='forge_analytics_job_trends'),
    re_path(r'^success_rate/$', SuccessRateView.as_view(), name='forge_analytics_success_rate'),
    re_path(r'^top_templates/$', TopTemplatesView.as_view(), name='forge_analytics_top_templates'),
    re_path(r'^busiest_hosts/$', BusiestHostsView.as_view(), name='forge_analytics_busiest_hosts'),
    re_path(r'^host_coverage/$', HostCoverageView.as_view(), name='forge_analytics_host_coverage'),
    re_path(r'^failure_analysis/$', FailureAnalysisView.as_view(), name='forge_analytics_failure_analysis'),
    re_path(r'^time_savings/$', TimeSavingsView.as_view(), name='forge_analytics_time_savings'),
]
