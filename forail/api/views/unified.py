# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

import html
import re
from base64 import b64encode

from django.utils.safestring import mark_safe
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

import ansiconv
from wsgiref.util import FileWrapper

from rest_framework.renderers import JSONRenderer, StaticHTMLRenderer
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import get_view_name

from forail.main.utils import camelcase_to_underscore
from forail.main.redact import UriCleaner
from forail.api.generics import ListAPIView, RetrieveAPIView
from forail.api.views.mixin import redact_ansi, StdoutFilter
from forail.api import renderers
from forail.api import serializers
from forail.main import models


class UnifiedJobTemplateList(ListAPIView):
    model = models.UnifiedJobTemplate
    serializer_class = serializers.UnifiedJobTemplateSerializer
    search_fields = ('description', 'name', 'jobtemplate__playbook')


class UnifiedJobList(ListAPIView):
    model = models.UnifiedJob
    serializer_class = serializers.UnifiedJobListSerializer
    search_fields = ('description', 'name', 'job__playbook')


class UnifiedJobStdout(RetrieveAPIView):
    authentication_classes = api_settings.DEFAULT_AUTHENTICATION_CLASSES
    serializer_class = serializers.UnifiedJobStdoutSerializer
    renderer_classes = [
        renderers.BrowsableAPIRenderer,
        StaticHTMLRenderer,
        renderers.PlainTextRenderer,
        renderers.AnsiTextRenderer,
        JSONRenderer,
        renderers.DownloadTextRenderer,
        renderers.AnsiDownloadRenderer,
    ]
    filter_backends = ()

    def retrieve(self, request, *args, **kwargs):
        unified_job = self.get_object()
        try:
            target_format = request.accepted_renderer.format
            if target_format in ('html', 'api', 'json'):
                content_encoding = request.query_params.get('content_encoding', None)
                start_line = request.query_params.get('start_line', 0)
                end_line = request.query_params.get('end_line', None)
                dark_val = request.query_params.get('dark', '')
                dark = bool(dark_val and dark_val[0].lower() in ('1', 't', 'y'))
                content_only = bool(target_format in ('api', 'json'))
                dark_bg = (content_only and dark) or (not content_only and (dark or not dark_val))
                content, start, end, absolute_end = unified_job.result_stdout_raw_limited(start_line, end_line)

                # Remove any ANSI escape sequences containing job event data.
                content = re.sub(r'\x1b\[K(?:[A-Za-z0-9+/=]+\x1b\[\d+D)+\x1b\[K', '', content)

                body = ansiconv.to_html(html.escape(content))

                context = {'title': get_view_name(self.__class__), 'body': mark_safe(body), 'dark': dark_bg, 'content_only': content_only}
                data = render_to_string('api/stdout.html', context).strip()

                if target_format == 'api':
                    return Response(mark_safe(data))
                if target_format == 'json':
                    content = content.encode('utf-8')
                    if content_encoding == 'base64':
                        content = b64encode(content)
                    return Response({'range': {'start': start, 'end': end, 'absolute_end': absolute_end}, 'content': content})
                return Response(data)
            elif target_format == 'txt':
                return Response(unified_job.result_stdout)
            elif target_format == 'ansi':
                return Response(unified_job.result_stdout_raw)
            elif target_format in {'txt_download', 'ansi_download'}:
                filename = '{type}_{pk}{suffix}.txt'.format(
                    type=camelcase_to_underscore(unified_job.__class__.__name__), pk=unified_job.id, suffix='.ansi' if target_format == 'ansi_download' else ''
                )
                content_fd = unified_job.result_stdout_raw_handle(enforce_max_bytes=False)
                redactor = StdoutFilter(content_fd)
                if target_format == 'txt_download':
                    redactor.register(redact_ansi)
                if type(unified_job) == models.ProjectUpdate:
                    redactor.register(UriCleaner.remove_sensitive)
                response = HttpResponse(FileWrapper(redactor), content_type='text/plain')
                response["Content-Disposition"] = 'attachment; filename="{}"'.format(filename)
                return response
            else:
                return super(UnifiedJobStdout, self).retrieve(request, *args, **kwargs)
        except models.StdoutMaxBytesExceeded as e:
            response_message = _(
                "Standard Output too large to display ({text_size} bytes), only download supported for sizes over {supported_size} bytes."
            ).format(text_size=e.total, supported_size=e.supported)
            if request.accepted_renderer.format == 'json':
                return Response({'range': {'start': 0, 'end': 1, 'absolute_end': 1}, 'content': response_message})
            else:
                return Response(response_message)
