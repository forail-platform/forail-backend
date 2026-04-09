from django.urls import re_path

from forge.api.views.scanner import (
    ScannerList,
    ScannerDetail,
    ScannerToggle,
    ScanResultList,
    ScanResultDetail,
)

scanner_urls = [
    re_path(r'^$', ScannerList.as_view(), name='scanner_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', ScannerDetail.as_view(), name='scanner_detail'),
    re_path(r'^(?P<pk>[0-9]+)/(?P<action>enable|disable)/$', ScannerToggle.as_view(), name='scanner_toggle'),
]

scan_result_urls = [
    re_path(r'^$', ScanResultList.as_view(), name='scan_result_list'),
    re_path(r'^(?P<pk>[0-9]+)/$', ScanResultDetail.as_view(), name='scan_result_detail'),
]

__all__ = ['scanner_urls', 'scan_result_urls']
