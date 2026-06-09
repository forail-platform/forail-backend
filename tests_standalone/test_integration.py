"""
Integration test for dynamic surveys.
Runs with real Django LocMem cache (no database needed).
"""
import os
os.environ["DJANGO_SETTINGS_MODULE"] = "forail.settings.development"

import django.conf
django.conf.settings.configure(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    DATABASES={},
    INSTALLED_APPS=[],
    SECRET_KEY="test-secret-key",
)

from forail.main.services.dynamic_survey import (
    validate_dynamic_choices_config,
    resolve_dynamic_choices,
)

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


print("=== Validation Tests ===")

check("Valid DB query",
      validate_dynamic_choices_config({"enabled": True, "source_type": "db_query", "model": "hosts", "field": "name", "cache_ttl": 120}) == [])
check("Valid API endpoint",
      validate_dynamic_choices_config({"enabled": True, "source_type": "api_endpoint", "url": "https://example.com", "cache_ttl": 30}) == [])
check("Valid Jinja2",
      validate_dynamic_choices_config({"enabled": True, "source_type": "jinja2", "template": "{{ hosts }}", "cache_ttl": 60}) == [])
check("Disabled is valid",
      validate_dynamic_choices_config({"enabled": False}) == [])
check("Invalid source_type",
      len(validate_dynamic_choices_config({"enabled": True, "source_type": "graphql"})) > 0)
check("Invalid model",
      len(validate_dynamic_choices_config({"enabled": True, "source_type": "db_query", "model": "users"})) > 0)
check("Invalid field",
      len(validate_dynamic_choices_config({"enabled": True, "source_type": "db_query", "model": "hosts", "field": "secret"})) > 0)
check("Missing URL",
      len(validate_dynamic_choices_config({"enabled": True, "source_type": "api_endpoint"})) > 0)
check("Missing template",
      len(validate_dynamic_choices_config({"enabled": True, "source_type": "jinja2"})) > 0)
check("Negative TTL",
      len(validate_dynamic_choices_config({"enabled": True, "source_type": "db_query", "model": "hosts", "cache_ttl": -1})) > 0)
check("Not a dict",
      len(validate_dynamic_choices_config("bad")) > 0)

print()
print("=== Resolution Tests ===")

check("Disabled returns None",
      resolve_dynamic_choices({"variable": "x", "dynamic_choices": {"enabled": False}}) is None)
check("No DC returns None",
      resolve_dynamic_choices({"variable": "x", "type": "text"}) is None)

# Jinja2 tests
def jinja_test(name, template, expected):
    q = {
        "variable": "t",
        "type": "multiplechoice",
        "dynamic_choices": {
            "enabled": True,
            "source_type": "jinja2",
            "template": template,
            "cache_ttl": 0,
        },
    }
    result = resolve_dynamic_choices(q)
    check(name, result == expected)

jinja_test("Static JSON list", '["staging", "production"]', ["staging", "production"])
jinja_test("Range expression", "{{ range(1,4) | list | tojson }}", ["1", "2", "3"])
jinja_test("Empty template", "", [])
jinja_test("Filter expression", '{{ ["web-01", "web-02", "db-01"] | reject("equalto", "db-01") | list | tojson }}', ["web-01", "web-02"])

# Cache test
q_cached = {
    "variable": "cache_test",
    "type": "multiplechoice",
    "dynamic_choices": {
        "enabled": True,
        "source_type": "jinja2",
        "template": '["a", "b", "c"]',
        "cache_ttl": 60,
    },
}
r1 = resolve_dynamic_choices(q_cached)
r2 = resolve_dynamic_choices(q_cached)
check("Cache works (same result)", r1 == r2 == ["a", "b", "c"])

# API with bad URL
q_bad_api = {
    "variable": "bad",
    "type": "multiplechoice",
    "dynamic_choices": {
        "enabled": True,
        "source_type": "api_endpoint",
        "url": "https://nonexistent.invalid/api",
        "cache_ttl": 0,
    },
}
r_bad = resolve_dynamic_choices(q_bad_api)
check("Bad API returns empty list", r_bad == [])

# Unknown source type
q_unknown = {
    "variable": "u",
    "type": "multiplechoice",
    "dynamic_choices": {
        "enabled": True,
        "source_type": "unknown",
        "cache_ttl": 0,
    },
}
r_unknown = resolve_dynamic_choices(q_unknown)
check("Unknown source returns empty", r_unknown == [])

print()
print(f"Results: {passed} passed, {failed} failed")
if failed == 0:
    print("=" * 50)
    print("ALL INTEGRATION TESTS PASSED!")
    print("=" * 50)
else:
    print("SOME TESTS FAILED!")
    exit(1)
