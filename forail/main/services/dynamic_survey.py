import hashlib
import json
import logging
import time

import requests
from django.apps import apps
from django.core.cache import cache

logger = logging.getLogger('forail.main.services.dynamic_survey')

DYNAMIC_CHOICES_CACHE_PREFIX = 'dynamic_survey_choices_'
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

    Config format:
    {
        "template": "{{ groups | map(attribute='name') | list }}"
    }

    Available context variables:
    - hosts: list of host names from the template's inventory
    - groups: list of group names from the template's inventory
    """
    try:
        from jinja2 import Environment, BaseLoader, StrictUndefined
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
        env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        tmpl = env.from_string(template_str)
        result = tmpl.render(**context)

        # Try to parse as JSON list
        parsed = json.loads(result)
        if isinstance(parsed, list):
            return parsed
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
