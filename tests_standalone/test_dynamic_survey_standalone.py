"""
Standalone tests for dynamic survey service.
These tests do not require Django setup — they mock all Django dependencies.
"""
import json
import sys
import os
from unittest.mock import patch, MagicMock, PropertyMock

# Mock Django modules before importing our code.
#
# django.db has to be stubbed alongside the rest: forail/__init__.py does
# `from django.db import connection` at import time, and a bare MagicMock under
# 'django' is not a package, so that line is what used to make this file
# uncollectable on its own. It was excluded from CI for it.
sys.modules['django'] = MagicMock()
sys.modules['django.apps'] = MagicMock()
sys.modules['django.core'] = MagicMock()
sys.modules['django.core.cache'] = MagicMock()
sys.modules['django.conf'] = MagicMock()
sys.modules['django.db'] = MagicMock()

import pytest

# Now we can import after mocking Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Re-import with fresh mocks
if 'forail.main.services.dynamic_survey' in sys.modules:
    del sys.modules['forail.main.services.dynamic_survey']

from forail.main.services import dynamic_survey
from forail.main.services.dynamic_survey import (
    validate_dynamic_choices_config,
    _resolve_api_endpoint,
    _resolve_jinja2,
    _resolve_db_query,
    resolve_dynamic_choices,
    ALLOWED_DB_MODELS,
    ALLOWED_DB_FIELDS,
)


class _Settings:
    """Stands in for django.conf.settings.

    The real settings object is a MagicMock here, and every attribute of a
    MagicMock is truthy -- which would silently enable the jinja2 source type
    in every test. The service reads the flag with `is True` for that reason;
    this class lets a test say which value it wants.
    """

    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def jinja2_enabled(value=True):
    """Patch the service's settings so the jinja2 source type is on/off."""
    return patch.object(
        dynamic_survey, 'settings', _Settings(SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED=value)
    )


# ===== validate_dynamic_choices_config =====

class TestValidation:

    def test_valid_db_query(self):
        dc = {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'field': 'name', 'cache_ttl': 60}
        assert validate_dynamic_choices_config(dc) == []

    def test_valid_api_endpoint(self):
        dc = {'enabled': True, 'source_type': 'api_endpoint', 'url': 'https://example.com/api', 'cache_ttl': 30}
        assert validate_dynamic_choices_config(dc) == []

    def test_jinja2_rejected_by_default(self):
        # The source type executes a template in the web process, so a survey
        # spec may not even be saved with it unless an operator opted in.
        dc = {'enabled': True, 'source_type': 'jinja2', 'template': '{{ hosts }}', 'cache_ttl': 10}
        errors = validate_dynamic_choices_config(dc)
        assert len(errors) == 1
        assert 'SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED' in errors[0]

    def test_valid_jinja2_when_operator_enabled(self):
        dc = {'enabled': True, 'source_type': 'jinja2', 'template': '{{ hosts }}', 'cache_ttl': 10}
        with jinja2_enabled():
            assert validate_dynamic_choices_config(dc) == []

    def test_jinja2_not_enabled_by_a_truthy_value(self):
        # A stray "true"/1 in a settings file must not turn code execution on.
        dc = {'enabled': True, 'source_type': 'jinja2', 'template': '{{ hosts }}'}
        for value in ('True', 'true', 1, [1]):
            with jinja2_enabled(value):
                errors = validate_dynamic_choices_config(dc)
                assert errors, f'{value!r} should not enable the jinja2 source type'

    def test_disabled_always_valid(self):
        assert validate_dynamic_choices_config({'enabled': False}) == []

    def test_not_dict(self):
        errors = validate_dynamic_choices_config("bad")
        assert len(errors) == 1
        assert "dictionary" in errors[0]

    def test_missing_enabled(self):
        errors = validate_dynamic_choices_config({'source_type': 'db_query'})
        assert len(errors) == 1
        assert "'enabled'" in errors[0]

    def test_bad_source_type(self):
        errors = validate_dynamic_choices_config({'enabled': True, 'source_type': 'magic'})
        assert len(errors) == 1
        assert "source_type" in errors[0]

    def test_invalid_model(self):
        dc = {'enabled': True, 'source_type': 'db_query', 'model': 'users'}
        errors = validate_dynamic_choices_config(dc)
        assert any("model" in e for e in errors)

    def test_invalid_field(self):
        dc = {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'field': 'secret'}
        errors = validate_dynamic_choices_config(dc)
        assert any("field" in e for e in errors)

    def test_api_missing_url(self):
        dc = {'enabled': True, 'source_type': 'api_endpoint'}
        errors = validate_dynamic_choices_config(dc)
        assert any("url" in e for e in errors)

    def test_jinja2_missing_template(self):
        dc = {'enabled': True, 'source_type': 'jinja2'}
        with jinja2_enabled():
            errors = validate_dynamic_choices_config(dc)
        assert any("template" in e for e in errors)

    def test_negative_ttl(self):
        dc = {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'cache_ttl': -5}
        errors = validate_dynamic_choices_config(dc)
        assert any("cache_ttl" in e for e in errors)

    def test_all_allowed_models(self):
        for model in ALLOWED_DB_MODELS:
            dc = {'enabled': True, 'source_type': 'db_query', 'model': model}
            errors = validate_dynamic_choices_config(dc)
            assert not any("model" in e for e in errors), f"Model '{model}' should be allowed"

    def test_all_allowed_fields(self):
        for field in ALLOWED_DB_FIELDS:
            dc = {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'field': field}
            errors = validate_dynamic_choices_config(dc)
            assert not any("field" in e for e in errors), f"Field '{field}' should be allowed"


# ===== _resolve_api_endpoint =====

class TestApiEndpoint:

    @patch('forail.main.services.dynamic_survey.requests')
    def test_simple_list(self, mock_req):
        resp = MagicMock()
        resp.json.return_value = ['a', 'b', 'c']
        resp.raise_for_status = MagicMock()
        mock_req.get.return_value = resp

        result = _resolve_api_endpoint({'url': 'https://example.com/list'})
        assert result == ['a', 'b', 'c']

    @patch('forail.main.services.dynamic_survey.requests')
    def test_json_path(self, mock_req):
        resp = MagicMock()
        resp.json.return_value = {'data': {'items': ['x', 'y']}}
        resp.raise_for_status = MagicMock()
        mock_req.get.return_value = resp

        result = _resolve_api_endpoint({'url': 'https://example.com', 'json_path': 'data.items'})
        assert result == ['x', 'y']

    @patch('forail.main.services.dynamic_survey.requests')
    def test_value_field(self, mock_req):
        resp = MagicMock()
        resp.json.return_value = [{'name': 'srv1'}, {'name': 'srv2'}]
        resp.raise_for_status = MagicMock()
        mock_req.get.return_value = resp

        result = _resolve_api_endpoint({'url': 'https://example.com', 'value_field': 'name'})
        assert result == ['srv1', 'srv2']

    @patch('forail.main.services.dynamic_survey.requests')
    def test_post_method(self, mock_req):
        resp = MagicMock()
        resp.json.return_value = ['p1', 'p2']
        resp.raise_for_status = MagicMock()
        mock_req.post.return_value = resp

        result = _resolve_api_endpoint({'url': 'https://example.com', 'method': 'POST', 'body': {}})
        assert result == ['p1', 'p2']
        mock_req.post.assert_called_once()

    def test_empty_url(self):
        assert _resolve_api_endpoint({'url': ''}) == []

    @patch('forail.main.services.dynamic_survey.requests')
    def test_error_returns_empty(self, mock_req):
        mock_req.get.side_effect = Exception("fail")
        assert _resolve_api_endpoint({'url': 'https://bad.example.com'}) == []

    @patch('forail.main.services.dynamic_survey.requests')
    def test_non_list_response(self, mock_req):
        resp = MagicMock()
        resp.json.return_value = {"not": "a list"}
        resp.raise_for_status = MagicMock()
        mock_req.get.return_value = resp

        result = _resolve_api_endpoint({'url': 'https://example.com'})
        assert result == []


# ===== _resolve_jinja2 =====

class TestJinja2:
    """The renderer, with the source type turned on by an operator."""

    def test_static_list(self):
        with jinja2_enabled():
            result = _resolve_jinja2({'template': '["opt1", "opt2"]'})
        assert result == ['opt1', 'opt2']

    def test_empty_template(self):
        with jinja2_enabled():
            assert _resolve_jinja2({'template': ''}) == []

    def test_invalid_output(self):
        # Non-JSON result
        with jinja2_enabled():
            result = _resolve_jinja2({'template': 'not json'})
        assert result == []

    def test_filters_still_work(self):
        with jinja2_enabled():
            result = _resolve_jinja2({'template': '{{ ["b", "a", "b"] | unique | sort | list | tojson }}'})
        assert result == ['a', 'b']

    def test_result_is_capped(self):
        with jinja2_enabled():
            result = _resolve_jinja2({'template': '{{ (["x"] * 600) | list | tojson }}'})
        assert len(result) == 500


class TestJinja2Disabled:
    """Default posture: the template is never rendered at all."""

    def test_renderer_refuses(self):
        # A template that would raise if it were rendered proves the renderer
        # was never reached, not merely that the output was discarded.
        assert _resolve_jinja2({'template': '["ran"]'}) == []

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_jinja2')
    def test_dispatch_does_not_call_the_renderer(self, mock_jinja, mock_cache):
        # Survey specs saved before the source type was refused still sit in the
        # database; resolving one must not execute it.
        mock_cache.get.return_value = None
        q = {
            'variable': 'v',
            'dynamic_choices': {
                'enabled': True,
                'source_type': 'jinja2',
                'template': '{{ cycler.__init__.__globals__ }}',
                'cache_ttl': 10,
            },
        }
        assert resolve_dynamic_choices(q) == []
        mock_jinja.assert_not_called()

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_jinja2')
    def test_refusal_is_not_cached(self, mock_jinja, mock_cache):
        # Caching the empty result would mask the warning for the whole TTL.
        mock_cache.get.return_value = None
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'jinja2', 'cache_ttl': 300}}
        resolve_dynamic_choices(q)
        mock_cache.set.assert_not_called()


# Known template-to-Python routes. These are the expressions the original
# unsandboxed Environment answered: `{{ cycler.__init__.__globals__.os.name }}`
# returned `posix`, which is a read from the module table and one attribute away
# from `os.system`.
JINJA2_ESCAPES = [
    "{{ cycler.__init__.__globals__.os.name }}",
    "{{ cycler.__init__.__globals__['os'].name }}",
    "{{ joiner.__init__.__globals__ }}",
    "{{ namespace.__init__.__globals__ }}",
    "{{ ''.__class__.__mro__[1].__subclasses__() }}",
    "{{ ''.__class__.__base__.__subclasses__() }}",
    "{{ [].__class__.__base__.__subclasses__() }}",
    "{{ lipsum.__globals__ }}",
    "{{ self._TemplateReference__context }}",
    "{{ config }}",
    "{{ request }}",
    "{{ ''.__class__.__mro__[1].__subclasses__()[0].__init__.__globals__ }}",
]


class TestJinja2SandboxEscapes:
    """The escapes above, asserted against the operator-enabled path."""

    @pytest.mark.parametrize('expression', JINJA2_ESCAPES)
    def test_escape_yields_no_choices(self, expression):
        with jinja2_enabled():
            assert _resolve_jinja2({'template': expression}) == []

    @pytest.mark.parametrize('expression', JINJA2_ESCAPES)
    def test_escape_never_reaches_the_module_table(self, expression):
        # Wrapping the expression in a JSON list matters: rendered bare, an
        # escape returns a Python repr that fails json.loads, so the empty
        # result would prove nothing. Wrapped, a successful escape parses
        # cleanly and comes back as a populated list. Against the pre-fix
        # renderer this exact shape returned ['x', 'posix'] for the cycler
        # payload, and the PATH environment variable for its os.environ variant.
        with jinja2_enabled():
            result = _resolve_jinja2({'template': '["x", "' + expression + '"]'})
        assert result == []

    def test_globals_are_gone(self):
        # range/dict/lipsum/cycler/namespace/joiner are removed outright, so the
        # escape above has nothing to start from even before the sandbox runs.
        with jinja2_enabled():
            for name in ('range', 'dict', 'lipsum', 'cycler', 'namespace', 'joiner'):
                assert _resolve_jinja2({'template': f'{{{{ {name} }}}}'}) == []

    def test_disallowed_filter_is_gone(self):
        with jinja2_enabled():
            assert _resolve_jinja2({'template': "{{ ['a'] | pprint }}"}) == []


# ===== _resolve_db_query =====

class TestDbQuery:

    def test_invalid_model(self):
        assert _resolve_db_query({'model': 'bad_model', 'field': 'name'}) == []

    def test_invalid_field(self):
        assert _resolve_db_query({'model': 'hosts', 'field': 'password'}) == []

    @patch('forail.main.services.dynamic_survey.apps')
    def test_valid_query(self, mock_apps):
        mock_qs = MagicMock()
        mock_qs.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value.__getitem__ = MagicMock(
            return_value=['h1', 'h2']
        )
        mock_model = MagicMock()
        mock_model.objects = mock_qs
        mock_apps.get_model.return_value = mock_model

        result = _resolve_db_query({'model': 'hosts', 'field': 'name', 'filter': {'inventory__id': 1}})
        assert result == ['h1', 'h2']

    @patch('forail.main.services.dynamic_survey.apps')
    def test_auto_inventory_filter(self, mock_apps):
        mock_qs = MagicMock()
        mock_qs.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value.__getitem__ = MagicMock(
            return_value=['h1']
        )
        mock_model = MagicMock()
        mock_model.objects = mock_qs
        mock_apps.get_model.return_value = mock_model

        template = MagicMock()
        template.inventory_id = 42

        result = _resolve_db_query({'model': 'hosts', 'field': 'name'}, template=template)
        # Should have added inventory__id filter
        mock_qs.filter.assert_called_once()
        call_kwargs = mock_qs.filter.call_args[1]
        assert call_kwargs.get('inventory__id') == 42


# ===== resolve_dynamic_choices (top-level) =====

class TestResolveDynamicChoices:

    @patch('forail.main.services.dynamic_survey.cache')
    def test_disabled_returns_none(self, mock_cache):
        q = {'variable': 'v', 'dynamic_choices': {'enabled': False}}
        assert resolve_dynamic_choices(q) is None

    @patch('forail.main.services.dynamic_survey.cache')
    def test_no_dc_returns_none(self, mock_cache):
        assert resolve_dynamic_choices({'variable': 'v'}) is None

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_db_query')
    def test_cache_hit(self, mock_resolve, mock_cache):
        mock_cache.get.return_value = ['c1', 'c2']
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'cache_ttl': 60}}
        result = resolve_dynamic_choices(q)
        assert result == ['c1', 'c2']
        mock_resolve.assert_not_called()

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_db_query')
    def test_cache_miss(self, mock_resolve, mock_cache):
        mock_cache.get.return_value = None
        mock_resolve.return_value = ['h1', 'h2']
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'cache_ttl': 120}}
        result = resolve_dynamic_choices(q)
        assert result == ['h1', 'h2']
        mock_cache.set.assert_called_once()
        # Verify TTL is passed
        assert mock_cache.set.call_args[1]['timeout'] == 120

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_api_endpoint')
    def test_api_source(self, mock_resolve, mock_cache):
        mock_cache.get.return_value = None
        mock_resolve.return_value = ['a1', 'a2']
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'api_endpoint', 'url': 'http://x', 'cache_ttl': 30}}
        result = resolve_dynamic_choices(q)
        assert result == ['a1', 'a2']

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_jinja2')
    def test_jinja2_source(self, mock_resolve, mock_cache):
        mock_cache.get.return_value = None
        mock_resolve.return_value = ['j1', 'j2']
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'jinja2', 'template': '{{ x }}', 'cache_ttl': 10}}
        with jinja2_enabled():
            result = resolve_dynamic_choices(q)
        assert result == ['j1', 'j2']

    @patch('forail.main.services.dynamic_survey.cache')
    def test_unknown_source_returns_empty(self, mock_cache):
        mock_cache.get.return_value = None
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'unknown', 'cache_ttl': 0}}
        result = resolve_dynamic_choices(q)
        assert result == []

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_db_query')
    def test_results_are_stringified(self, mock_resolve, mock_cache):
        mock_cache.get.return_value = None
        mock_resolve.return_value = [1, 2.5, True]
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'cache_ttl': 60}}
        result = resolve_dynamic_choices(q)
        assert result == ['1', '2.5', 'True']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
