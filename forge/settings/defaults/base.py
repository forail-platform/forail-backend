# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Python
import base64
import os
import re  # noqa
import socket


DEBUG = True
SQL_DEBUG = DEBUG

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
# Extra os.path.dirname because this file is now inside defaults/ subdirectory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

# FIXME: it would be nice to cycle back around and allow this to be
# BigAutoField going forward, but we'd have to be explicit about our
# existing models.
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'forge.sqlite3'),
        'ATOMIC_REQUESTS': True,
        'TEST': {
            # Test database cannot be :memory: for inventory tests.
            'NAME': os.path.join(BASE_DIR, 'awx_test.sqlite3')
        },
    }
}

# Special database overrides for dispatcher connections listening to pg_notify
LISTENER_DATABASES = {
    'default': {
        'OPTIONS': {
            'keepalives': 1,
            'keepalives_idle': 5,
            'keepalives_interval': 5,
            'keepalives_count': 5,
        },
    }
}

# Whether or not the deployment is a K8S-based deployment
# In K8S-based deployments, instances have zero capacity - all playbook
# automation is intended to flow through defined Container Groups that
# interface with some (or some set of) K8S api (which may or may not include
# the K8S cluster where awx itself is running)
IS_K8S = False

AWX_CONTAINER_GROUP_K8S_API_TIMEOUT = 10
AWX_CONTAINER_GROUP_DEFAULT_NAMESPACE = os.getenv('MY_POD_NAMESPACE', 'default')
# Timeout when waiting for pod to enter running state. If the pod is still in pending state , it will be terminated. Valid time units are "s", "m", "h". Example : "5m" , "10s".
AWX_CONTAINER_GROUP_POD_PENDING_TIMEOUT = "2h"

# How much capacity controlling a task costs a hybrid or control node
AWX_CONTROL_NODE_TASK_IMPACT = 1

# Internationalization
# https://docs.djangoproject.com/en/dev/topics/i18n/
#
# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# On Unix systems, a value of None will cause Django to use the same
# timezone as the operating system.
# If running in a Windows environment this must be set to the same as your
# system time zone.
TIME_ZONE = 'UTC'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# If you set this to False, Django will not format dates, numbers and
# calendars according to the current locale
USE_L10N = True

USE_TZ = True

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'ui', 'build', 'static'),
    os.path.join(BASE_DIR, 'ui_next', 'build'),
    os.path.join(BASE_DIR, 'static'),
]

# Absolute filesystem path to the directory where static file are collected via
# the collectstatic command.
STATIC_ROOT = '/var/lib/awx/public/static'

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/dev/howto/static-files/
STATIC_URL = '/static/'

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = os.path.join(BASE_DIR, 'public', 'media')

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = '/media/'

LOGIN_URL = '/api/login/'
LOGOUT_ALLOWED_HOSTS = None

# Absolute filesystem path to the directory to host projects (with playbooks).
# This directory should not be web-accessible.
PROJECTS_ROOT = '/var/lib/awx/projects/'

# Absolute filesystem path to the directory for job status stdout (default for
# development and tests, default for production defined in production.py). This
# directory should not be web-accessible
JOBOUTPUT_ROOT = '/var/lib/awx/job_status/'

# Absolute filesystem path to the directory to store logs
LOG_ROOT = '/var/log/tower/'

# Django gettext files path: locale/<lang-code>/LC_MESSAGES/django.po, django.mo
LOCALE_PATHS = (os.path.join(BASE_DIR, 'locale'),)

# Graph of resources that can have named-url
NAMED_URL_GRAPH = {}

# Maximum number of the same job that can be waiting to run when launching from scheduler
# Note: This setting may be overridden by database settings.
SCHEDULE_MAX_JOBS = 10

# Bulk API related settings
# Maximum number of jobs that can be launched in 1 bulk job
BULK_JOB_MAX_LAUNCH = 100

# Maximum number of host that can be created in 1 bulk host create
BULK_HOST_MAX_CREATE = 100

# Maximum number of host that can be deleted in 1 bulk host delete
BULK_HOST_MAX_DELETE = 250

SITE_ID = 1

# Make this unique, and don't share it with anybody.
if os.path.exists('/etc/tower/SECRET_KEY'):
    with open('/etc/tower/SECRET_KEY', 'rb') as f:
        SECRET_KEY = f.read().strip()
else:
    SECRET_KEY = base64.encodebytes(os.urandom(32)).decode().rstrip()

# Hosts/domain names that are valid for this site; required if DEBUG is False
# See https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = []

# HTTP headers and meta keys to search to determine remote host name or IP. Add
# additional items to this list, such as "HTTP_X_FORWARDED_FOR", if behind a
# reverse proxy.
REMOTE_HOST_HEADERS = ['REMOTE_ADDR', 'REMOTE_HOST']

# If we are behind a reverse proxy/load balancer, use this setting to
# allow the proxy IP addresses from which Tower should trust custom
# REMOTE_HOST_HEADERS header values
# REMOTE_HOST_HEADERS = ['HTTP_X_FORWARDED_FOR', ''REMOTE_ADDR', 'REMOTE_HOST']
# PROXY_IP_ALLOWED_LIST = ['10.0.1.100', '10.0.1.101']
# If this setting is an empty list (the default), the headers specified by
# REMOTE_HOST_HEADERS will be trusted unconditionally')
PROXY_IP_ALLOWED_LIST = []

# If we are behind a reverse proxy/load balancer, use this setting to
# allow the scheme://addresses from which Tower should trust csrf requests from
# If this setting is an empty list (the default), we will only trust ourself
CSRF_TRUSTED_ORIGINS = []

CUSTOM_VENV_PATHS = []

TEMPLATES = [
    {
        'NAME': 'default',
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [  # NOQA
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.i18n',
                'django.template.context_processors.media',
                'django.template.context_processors.static',
                'django.template.context_processors.tz',
                'django.contrib.messages.context_processors.messages',
                'forge.ui.context_processors.csp',
                'forge.ui.context_processors.version',
                'social_django.context_processors.backends',
                'social_django.context_processors.login_redirect',
            ],
            'builtins': ['forge.main.templatetags.swagger'],
        },
        'DIRS': [
            os.path.join(BASE_DIR, 'templates'),
            os.path.join(BASE_DIR, 'ui', 'build'),
            os.path.join(BASE_DIR, 'ui', 'public'),
            os.path.join(BASE_DIR, 'ui_next', 'build', 'forge'),
        ],
    },
]

ROOT_URLCONF = 'forge.urls'

WSGI_APPLICATION = 'forge.wsgi.application'

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.messages',
    'django.contrib.sessions',
    'django.contrib.sites',
    # daphne has to be installed before django.contrib.staticfiles for the app to startup
    # According to channels 4.0 docs you install daphne instead of channels now
    'daphne',
    'django.contrib.staticfiles',
    'oauth2_provider',
    'rest_framework',
    'django_extensions',
    'polymorphic',
    'social_django',
    'django_guid',
    'corsheaders',
    'forge.conf',
    'forge.main',
    'forge.api',
    'forge.ui',
    'forge.sso',
    'solo',
    'ansible_base.rest_filters',
    'ansible_base.jwt_consumer',
    'ansible_base.resource_registry',
    'ansible_base.rbac',
]


INTERNAL_IPS = ('127.0.0.1',)

# https://github.com/django-polymorphic/django-polymorphic/issues/195
# FIXME: Disabling models.E006 warning until we can renamed Project and InventorySource
SILENCED_SYSTEM_CHECKS = ['models.E006']

MIDDLEWARE = [
    # Request ID tracing - must be first to tag all subsequent processing
    'django_guid.middleware.guid_middleware',
    # Clear settings cache for fresh values each request
    'forge.main.middleware.SettingsCacheMiddleware',
    # Request timing/profiling (lightweight when AWX_REQUEST_PROFILE=False)
    'forge.main.middleware.TimingMiddleware',
    # CORS headers - must be before any middleware that can generate responses
    'corsheaders.middleware.CorsMiddleware',
    # --- Django core middleware ---
    'django.contrib.sessions.middleware.SessionMiddleware',
    # Redirect if migrations not applied
    'forge.main.middleware.MigrationRanCheckMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Must be after AuthenticationMiddleware - needs request.user
    'forge.main.middleware.DisableLocalAuthMiddleware',
    # Enforces org-level WebAuthn MFA after primary auth
    'forge.main.middleware.WebAuthnMfaEnforcementMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # URL routing based on optional prefix
    'forge.main.middleware.OptionalURLPrefixPath',
    # Social auth handling (extends SocialAuthExceptionMiddleware)
    'forge.sso.middleware.SocialAuthMiddleware',
    # Makes current request/user available via crum.get_current_user()
    'crum.CurrentRequestUserMiddleware',
    # Named URL to PK conversion (e.g. /api/v2/users/admin/ -> /api/v2/users/1/)
    'forge.main.middleware.URLModificationMiddleware',
    # Session timeout refresh - must be last to set response headers
    'forge.main.middleware.SessionTimeoutMiddleware',
]

# This is overridden downstream via /etc/tower/conf.d/cluster_host_id.py
CLUSTER_HOST_ID = socket.gethostname()

UI_LEGACY_ENABLED = True
