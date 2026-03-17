from django.urls import re_path
from django.views.generic.base import TemplateView


class IndexView(TemplateView):
    template_name = 'index_forge.html'


app_name = 'ui_next'

# Catch-all: every path is handled by the SPA's client-side router
urlpatterns = [re_path(r'^.*$', IndexView.as_view(), name='index')]
