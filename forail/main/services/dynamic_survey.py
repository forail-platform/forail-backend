import hashlib
import json
import logging
import time

import requests
from django.apps import apps
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger('forail.main.services.dynamic_survey')

DYNAMIC_CHOICES_CACHE_PREFIX = 'dynamic_survey_choices_'

# Jinja2 as a choices source is a code-execution surface, not a formatting
# convenience: the template text is supplied by whoever may edit a job
# template's survey spec, and it is rendered inside the web process when any
# user with `start` permission opens the launch prompt. Rendering it through a
# plain Environment hands that user Python -- `{{ cycler.__init__.__globals__ }}`
# is the standard route from a template to the module table.
#
# So the source type is refused unless an operator turns it on, and the switch
# is a settings *file* value on purpose -- deliberately not a database-backed
# setting exposed over /api/v2/settings/. The same API surface used to plant a
# payload must not also be able to enable its execution.
SURVEY_DYNAMIC_CHOICES_JINJA2_SETTING = 'SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED'

# Filters left reachable when an operator does enable the source type. Jinja2
# seeds an environment with far more than a choices list needs; what is not
# here is removed rather than trusted to the sandbox.
JINJA2_ALLOWED_FILTERS = frozenset(
    {
        'batch',
        'default',
        'first',
        'int',
        'join',
        'last',
        'length',
        'list',
        'lower',
        'map',
        'reject',
        'replace',
        'reverse',
        'select',
        'sort',
        'string',
        'tojson',
        'trim',
        'unique',
        'upper',
    }
)

# Same ceiling the DB source applies, for the same reason: a choices list is a
# dropdown, not a data export.
MAX_CHOICES = 500


def jinja2_source_enabled():
    """
    Whether the jinja2 dynamic_choices source type may be used.

    The comparison is `is True` rather than a truth test on purpose: a stray
    string, a `1`, or a test double standing in for the settings object must
    not be enough to turn a code-execution path back on.
    """
    return getattr(settings, SURVEY_DYNAMIC_CHOICES_JINJA2_SETTING, False) is True
ALLOWED_DB_MODELS = {
    'hosts': ('main', 'Host'),
    'groups': ('main', 'Group'),
    'projects': ('main', 'Project'),
    'inventories': ('main', 'Inventory'),
    'credentials': ('main', 'Credential'),
    'organizations': ('main', 'Organization'),
    'execution_environments': ('main', 'ExecutionEnvironment'),
    'templates': ('main', 'JobTemplate'),
}

ALLOWED_DB_FIELDS = {'name', 'id', 'description'}


def _cache_key(question_variable, source_config):
    config_hash = hashlib.md5(json.dumps(source_config, sort_keys=True).encode()).hexdigest()
    return f'{DYNAMIC_CHOICES_CACHE_PREFIX}{question_variable}_{config_hash}'


def resolve_dynamic_choices(question, template=None):
    """
    Resolve dynamic choices for a single survey question.

    Returns a list of strings (choice values).
    """
    dc = question.get('dynamic_choices')
    if not dc or not dc.get('enabled'):
        return None

    source_type = dc.get('source_type')
    cache_ttl = dc.get('cache_ttl', 60)
    variable = question.get('variable', '')

    # Check cache
    ck = _cache_key(variable, dc)
    cached = cache.get(ck)
    if cached is not None:
        return cached

    choices = []
    try:
        if source_type == 'db_query':
            choices = _resolve_db_query(dc, template)
        elif source_type == 'api_endpoint':
            choices = _resolve_api_endpoint(dc)
        elif source_type == 'jinja2':
            # Reached only by survey specs stored before the config validation
            # below started rejecting this source type. Refuse rather than
            # render: the payload is already in the database, and this is the
            # call that would execute it.
            if not jinja2_source_enabled():
                logger.warning(
                    'Refusing to render a jinja2 dynamic_choices template for survey variable %s: '
                    'the jinja2 source type is disabled (%s is not True). The stored survey spec '
                    'predates the validation that now rejects it.',
                    variable,
                    SURVEY_DYNAMIC_CHOICES_JINJA2_SETTING,
                )
                return []
            choices = _resolve_jinja2(dc, template)
        else:
            logger.warning('Unknown dynamic_choices source_type: %s', source_type)
            return []
    except Exception:
        logger.exception('Error resolving dynamic choices for variable %s', variable)
        return []

    # Ensure all choices are strings
    choices = [str(c) for c in choices]

    # Cache results
    if cache_ttl and cache_ttl > 0:
        cache.set(ck, choices, timeout=cache_ttl)

    return choices


def _resolve_db_query(dc, template=None):
    """
    Resolve choices from a database query.

    Config format:
    {
        "model": "hosts",          # key from ALLOWED_DB_MODELS
        "field": "name",           # field to use as choice value
        "filter": {                # optional filter kwargs
            "inventory__id": 1
        }
    }
    """
    model_key = dc.get('model', '')
    field = dc.get('field', 'name')
    filter_kwargs = dc.get('filter', {})

    if model_key not in ALLOWED_DB_MODELS:
        logger.warning('Dynamic choices: model %s not in allowed list', model_key)
        return []

    if field not in ALLOWED_DB_FIELDS:
        logger.warning('Dynamic choices: field %s not in allowed list', field)
        return []

    app_label, model_name = ALLOWED_DB_MODELS[model_key]
    Model = apps.get_model(app_label, model_name)

    # Sanitize filter kwargs — only allow safe lookups
    safe_kwargs = {}
    for key, value in filter_kwargs.items():
        parts = key.split('__')
        base_field = parts[0]
        # Allow filtering on common safe fields
        if base_field in ('id', 'name', 'inventory', 'organization', 'project', 'inventory_id', 'organization_id', 'project_id'):
            safe_kwargs[key] = value

    # If template has an inventory, allow implicit filtering
    if not safe_kwargs and template and model_key in ('hosts', 'groups'):
        inventory_id = getattr(template, 'inventory_id', None)
        if inventory_id:
            safe_kwargs['inventory__id'] = inventory_id

    try:
        qs = Model.objects.filter(**safe_kwargs).values_list(field, flat=True).distinct().order_by(field)[:500]
        return list(qs)
    except Exception:
        logger.exception('Dynamic choices DB query failed for model %s', model_key)
        return []


def _resolve_api_endpoint(dc):
    """
    Resolve choices from an external API endpoint.

    Config format:
    {
        "url": "https://api.example.com/options",
        "method": "GET",
        "headers": {"Authorization": "Bearer xxx"},   # optional
        "json_path": "data.items",                     # optional dot-notation path to array
        "value_field": "name",                         # optional field to extract from objects
        "timeout": 10                                  # optional, default 10s
    }
    """
    url = dc.get('url', '')
    if not url:
        return []

    method = dc.get('method', 'GET').upper()
    headers = dc.get('headers', {})
    timeout = dc.get('timeout', 10)
    json_path = dc.get('json_path', '')
    value_field = dc.get('value_field', '')

    try:
        if method == 'POST':
            body = dc.get('body', {})
            resp = requests.post(url, json=body, headers=headers, timeout=timeout)
        else:
            resp = requests.get(url, headers=headers, timeout=timeout)

        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception('Dynamic choices API request failed for %s', url)
        return []

    # Navigate JSON path
    if json_path:
        for key in json_path.split('.'):
            if isinstance(data, dict):
                data = data.get(key, [])
            elif isinstance(data, list) and key.isdigit():
                data = data[int(key)]
            else:
                return []

    if not isinstance(data, list):
        return []

    # Extract values
    if value_field:
        return [item.get(value_field, '') for item in data if isinstance(item, dict)]
    else:
        return [str(item) for item in data]


def _resolve_jinja2(dc, template=None):
    """
    Resolve choices from a Jinja2 template expression.

    Disabled unless ``SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED`` is True in the
    server settings file; see the note on that setting above. When it is on,
    the template is rendered in a sandbox with the globals removed and the
    filter set reduced to ``JINJA2_ALLOWED_FILTERS``.

    Even then the sandbox is a hardening measure, not a trust boundary --
    sandbox escapes are found periodically, and a template that renders in the
    web process is worth an escape to whoever plants it. Prefer db_query or
    api_endpoint.

    Config format:
    {
        "template": "{{ groups | sort | tojson }}"
    }

    Available context variables:
    - hosts: list of host names from the template's inventory
    - groups: list of group names from the template's inventory
    """
    if not jinja2_source_enabled():
        logger.warning(
            'Refusing to render a jinja2 dynamic_choices template: the jinja2 source type '
            'is disabled (%s is not True).',
            SURVEY_DYNAMIC_CHOICES_JINJA2_SETTING,
        )
        return []

    try:
        from jinja2 import BaseLoader, StrictUndefined
        from jinja2.sandbox import SandboxedEnvironment
    except ImportError:
        logger.error('Jinja2 is required for dynamic_choices jinja2 source_type')
        return []

    template_str = dc.get('template', '')
    if not template_str:
        return []

    # Build context
    context = {}
    if template:
        inventory_id = getattr(template, 'inventory_id', None)
        if inventory_id:
            Host = apps.get_model('main', 'Host')
            Group = apps.get_model('main', 'Group')
            context['hosts'] = list(Host.objects.filter(inventory_id=inventory_id).values_list('name', flat=True)[:500])
            context['groups'] = list(Group.objects.filter(inventory_id=inventory_id).values_list('name', flat=True)[:500])

    try:
        env = SandboxedEnvironment(loader=BaseLoader(), undefined=StrictUndefined)
        # Jinja2 seeds every environment with range, dict, lipsum, cycler,
        # namespace and joiner. cycler and joiner are class instances, which is
        # exactly what `{{ cycler.__init__.__globals__.os }}` walks. The sandbox
        # blocks that attribute access; there is still no reason to leave the
        # objects reachable.
        env.globals.clear()
        env.filters = {name: f for name, f in env.filters.items() if name in JINJA2_ALLOWED_FILTERS}
        env.tests = {}

        tmpl = env.from_string(template_str)
        result = tmpl.render(**context)

        # Try to parse as JSON list
        parsed = json.loads(result)
        if isinstance(parsed, list):
            return parsed[:MAX_CHOICES]
        return []
    except Exception:
        logger.exception('Dynamic choices Jinja2 evaluation failed')
        return []


def validate_dynamic_choices_config(dc):
    """
    Validate the dynamic_choices configuration on a survey question.
    Returns a list of error strings (empty = valid).
    """
    errors = []

    if not isinstance(dc, dict):
        errors.append("dynamic_choices must be a dictionary.")
        return errors

    if 'enabled' not in dc:
        errors.append("dynamic_choices must have an 'enabled' field.")
        return errors

    if not dc.get('enabled'):
        return errors

    source_type = dc.get('source_type', '')
    if source_type not in ('db_query', 'api_endpoint', 'jinja2'):
        errors.append(f"dynamic_choices source_type must be one of: db_query, api_endpoint, jinja2. Got '{source_type}'.")
        return errors

    if source_type == 'jinja2' and not jinja2_source_enabled():
        errors.append(
            "dynamic_choices source_type 'jinja2' is disabled: it renders a template supplied "
            "with the survey inside the server process. Use db_query or api_endpoint, or ask an "
            "administrator to set SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED = True in the server "
            "settings file."
        )
        return errors

    cache_ttl = dc.get('cache_ttl', 60)
    if not isinstance(cache_ttl, int) or cache_ttl < 0:
        errors.append("dynamic_choices cache_ttl must be a non-negative integer.")

    if source_type == 'db_query':
        model = dc.get('model', '')
        if model not in ALLOWED_DB_MODELS:
            errors.append(f"dynamic_choices model must be one of: {', '.join(ALLOWED_DB_MODELS.keys())}. Got '{model}'.")
        field = dc.get('field', 'name')
        if field not in ALLOWED_DB_FIELDS:
            errors.append(f"dynamic_choices field must be one of: {', '.join(ALLOWED_DB_FIELDS)}. Got '{field}'.")

    elif source_type == 'api_endpoint':
        url = dc.get('url', '')
        if not url or not isinstance(url, str):
            errors.append("dynamic_choices api_endpoint requires a non-empty 'url' string.")

    elif source_type == 'jinja2':
        tmpl = dc.get('template', '')
        if not tmpl or not isinstance(tmpl, str):
            errors.append("dynamic_choices jinja2 requires a non-empty 'template' string.")

    return errors
