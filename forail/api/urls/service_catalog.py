from django.urls import re_path

from forail.api.views.service_catalog import (
    ServiceCatalogItemList,
    ServiceCatalogItemDetail,
    ServiceCatalogItemLaunchData,
    ServiceCatalogItemRequestsList,
    ServiceCatalogItemSubmit,
    ServiceRequestList,
    ServiceRequestDetail,
    ServiceRequestApprove,
    ServiceRequestReject,
    ServiceRequestPendingApprovalsList,
)

service_catalog_item_urls = [
    re_path(r'^$', ServiceCatalogItemList.as_view(), name='service_catalog_item_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', ServiceCatalogItemDetail.as_view(), name='service_catalog_item_detail'),
    re_path(r'^(?P<pk>[0-9]+)/launch_data/$', ServiceCatalogItemLaunchData.as_view(), name='service_catalog_item_launch_data'),
    re_path(r'^(?P<pk>[0-9]+)/requests/$', ServiceCatalogItemRequestsList.as_view(), name='service_catalog_item_requests_list'),
    re_path(r'^(?P<pk>[0-9]+)/submit/$', ServiceCatalogItemSubmit.as_view(), name='service_catalog_item_submit'),
]

service_request_urls = [
    re_path(r'^$', ServiceRequestList.as_view(), name='service_request_list'),
    re_path(r'^pending_approvals/$', ServiceRequestPendingApprovalsList.as_view(), name='service_request_pending_approvals'),
    re_path(r'^(?P<pk>[0-9]+)/$', ServiceRequestDetail.as_view(), name='service_request_detail'),
    re_path(r'^(?P<pk>[0-9]+)/approve/$', ServiceRequestApprove.as_view(), name='service_request_approve'),
    re_path(r'^(?P<pk>[0-9]+)/reject/$', ServiceRequestReject.as_view(), name='service_request_reject'),
]

__all__ = ['service_catalog_item_urls', 'service_request_urls']
