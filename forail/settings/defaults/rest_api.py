# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# REST Framework configuration

import os


MAX_PAGE_SIZE = 200
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'forail.api.pagination.Pagination',
    'PAGE_SIZE': 25,
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'ansible_base.jwt_consumer.awx.auth.AwxJWTAuthentication',
        'forail.api.authentication.LoggedOAuth2Authentication',
        'forail.api.authentication.SessionAuthentication',
        'forail.api.authentication.LoggedBasicAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': ('forail.api.permissions.ModelAccessPermission',),
    'DEFAULT_PARSER_CLASSES': ('forail.api.parsers.JSONParser',),
    'DEFAULT_RENDERER_CLASSES': ('forail.api.renderers.DefaultJSONRenderer', 'forail.api.renderers.BrowsableAPIRenderer'),
    'DEFAULT_METADATA_CLASS': 'forail.api.metadata.Metadata',
    'EXCEPTION_HANDLER': 'forail.api.views.api_exception_handler',
    'VIEW_DESCRIPTION_FUNCTION': 'forail.api.generics.get_view_description',
    'NON_FIELD_ERRORS_KEY': '__all__',
    'DEFAULT_VERSION': 'v2',
    # For swagger schema generation
    # see https://github.com/encode/django-rest-framework/pull/6532
    'DEFAULT_SCHEMA_CLASS': 'rest_framework.schemas.AutoSchema',
    # 'URL_FORMAT_OVERRIDE': None,
}

DEVSERVER_DEFAULT_ADDR = '0.0.0.0'
DEVSERVER_DEFAULT_PORT = '8013'

# Set default ports for live server tests.
os.environ.setdefault('DJANGO_LIVE_TEST_SERVER_ADDRESS', 'localhost:9013-9199')
