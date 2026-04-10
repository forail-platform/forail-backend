from django.urls import re_path

from forge.api.views.tenancy import (
    TenantList,
    TenantDetail,
    TenantRecalculate,
    TenantQuotaEventList,
    TenantIsolationEventList,
    BrandingByHost,
)

tenant_urls = [
    re_path(r'^$', TenantList.as_view(), name='tenant_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', TenantDetail.as_view(), name='tenant_detail'),
    re_path(r'^(?P<pk>[0-9]+)/recalculate/$', TenantRecalculate.as_view(), name='tenant_recalculate'),
]

tenant_quota_event_urls = [
    re_path(r'^$', TenantQuotaEventList.as_view(), name='tenant_quota_event_list'),
]

tenant_isolation_event_urls = [
    re_path(r'^$', TenantIsolationEventList.as_view(), name='tenant_isolation_event_list'),
]

branding_urls = [
    re_path(r'^$', BrandingByHost.as_view(), name='branding_by_host'),
]

__all__ = ['tenant_urls', 'tenant_quota_event_urls', 'tenant_isolation_event_urls', 'branding_urls']
