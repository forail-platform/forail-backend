from django.urls import re_path

from forge.api.views.observability import ObservabilityConfig

observability_urls = [
    re_path(r'^$', ObservabilityConfig.as_view(), name='observability_config'),
]

__all__ = ['observability_urls']
