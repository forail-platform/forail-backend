"""
Standalone tests for dynamic survey service.
These tests do not require Django setup — they mock all Django dependencies.
"""
import json
import sys
import os
from unittest.mock import patch, MagicMock, PropertyMock

# Mock Django modules before importing our code
sys.modules['django'] = MagicMock()
sys.modules['django.apps'] = MagicMock()
sys.modules['django.core'] = MagicMock()
sys.modules['django.core.cache'] = MagicMock()
sys.modules['django.conf'] = MagicMock()

import pytest

# Now we can import after mocking Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Re-import with fresh mocks
if 'forail.main.services.dynamic_survey' in sys.modules:
    del sys.modules['forail.main.services.dynamic_survey']

from forail.main.services.dynamic_survey import (
    validate_dynamic_choices_config,
    _resolve_api_endpoint,
    _resolve_jinja2,
    _resolve_db_query,
    resolve_dynamic_choices,
    ALLOWED_DB_MODELS,
    ALLOWED_DB_FIELDS,
)


# ===== validate_dynamic_choices_config =====

class TestValidation:

    def test_valid_db_query(self):
        dc = {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'field': 'name', 'cache_ttl': 60}
        assert validate_dynamic_choices_config(dc) == []

    def test_valid_api_endpoint(self):
        dc = {'enabled': True, 'source_type': 'api_endpoint', 'url': 'https://example.com/api', 'cache_ttl': 30}
        assert validate_dynamic_choices_config(dc) == []

    def test_valid_jinja2(self):
        dc = {'enabled': True, 'source_type': 'jinja2', 'template': '{{ hosts }}', 'cache_ttl': 10}
        assert validate_dynamic_choices_config(dc) == []

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

    def test_static_list(self):
        result = _resolve_jinja2({'template': '["opt1", "opt2"]'})
        assert result == ['opt1', 'opt2']

    def test_empty_template(self):
        assert _resolve_jinja2({'template': ''}) == []

    def test_invalid_output(self):
        # Non-JSON result
        result = _resolve_jinja2({'template': 'not json'})
        assert result == []

    def test_expression_eval(self):
        result = _resolve_jinja2({'template': '{{ range(1,4) | list | tojson }}'})
        assert result == [1, 2, 3]


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
