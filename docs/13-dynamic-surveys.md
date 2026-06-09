# 13 — Dynamic Surveys

Dynamic surveys extend the standard survey system by allowing choice-based
questions (multiplechoice and multiselect) to populate their options at launch
time instead of at template definition time.

---

## Overview

Standard surveys require choices to be hardcoded in the survey spec. Dynamic
surveys resolve choices from three configurable sources:

| Source              | Description                                        | Use Case                            |
| ------------------- | -------------------------------------------------- | ----------------------------------- |
| **Database Query**  | Query Forail models (hosts, groups, projects, etc.) | Select a host from inventory        |
| **External API**    | Fetch choices from an HTTP endpoint                | Options from CMDB, ServiceNow, etc. |
| **Jinja2 Template** | Evaluate a Jinja2 expression                       | Custom logic using inventory data   |

Results are cached with a configurable TTL to avoid slow launches.

---

## Survey Spec Format

A survey question with dynamic choices includes a `dynamic_choices` field:

```json
{
  "name": "Deploy Survey",
  "description": "Select deployment target",
  "spec": [
    {
      "variable": "target_host",
      "question_name": "Select target host",
      "question_description": "Choose which host to deploy to",
      "type": "multiplechoice",
      "required": true,
      "default": "",
      "choices": "",
      "min": null,
      "max": null,
      "dynamic_choices": {
        "enabled": true,
        "source_type": "db_query",
        "model": "hosts",
        "field": "name",
        "filter": {
          "inventory__id": 1
        },
        "cache_ttl": 120
      }
    }
  ]
}
```

### dynamic_choices Configuration

| Field         | Type    | Required         | Description                                  |
| ------------- | ------- | ---------------- | -------------------------------------------- |
| `enabled`     | boolean | Yes              | Enable/disable dynamic choices               |
| `source_type` | string  | Yes (if enabled) | One of: `db_query`, `api_endpoint`, `jinja2` |
| `cache_ttl`   | integer | No (default: 60) | Cache duration in seconds (0 = no cache)     |

---

## Source: Database Query

Query Forail database models and return a field value as choices.

```json
{
  "enabled": true,
  "source_type": "db_query",
  "model": "hosts",
  "field": "name",
  "filter": {
    "inventory__id": 1,
    "name__startswith": "web"
  },
  "cache_ttl": 60
}
```

### Allowed Models

| Key                      | Model                | Example Use         |
| ------------------------ | -------------------- | ------------------- |
| `hosts`                  | Host                 | Select target hosts |
| `groups`                 | Group                | Select host groups  |
| `projects`               | Project              | Select project      |
| `inventories`            | Inventory            | Select inventory    |
| `credentials`            | Credential           | Select credential   |
| `organizations`          | Organization         | Select organization |
| `execution_environments` | ExecutionEnvironment | Select EE           |
| `templates`              | JobTemplate          | Select template     |

### Allowed Fields

- `name` — resource name (default)
- `id` — resource ID
- `description` — resource description

### Auto-filtering

If no filter is provided and the question type is `hosts` or `groups`,
the system automatically filters by the job template's inventory.

---

## Source: External API

Fetch choices from an HTTP endpoint. Supports JSON responses.

```json
{
  "enabled": true,
  "source_type": "api_endpoint",
  "url": "https://cmdb.example.com/api/v1/servers",
  "method": "GET",
  "headers": {
    "Authorization": "Bearer <token>"
  },
  "json_path": "data.items",
  "value_field": "hostname",
  "timeout": 10,
  "cache_ttl": 300
}
```

| Field         | Type    | Default | Description                                |
| ------------- | ------- | ------- | ------------------------------------------ |
| `url`         | string  | —       | HTTP endpoint URL (required)               |
| `method`      | string  | `GET`   | HTTP method (`GET` or `POST`)              |
| `headers`     | object  | `{}`    | Custom HTTP headers                        |
| `json_path`   | string  | `""`    | Dot-notation path to the array in response |
| `value_field` | string  | `""`    | Field to extract from objects in the array |
| `timeout`     | integer | `10`    | Request timeout in seconds                 |
| `body`        | object  | `{}`    | Request body for POST method               |

### Response Formats

**Simple list:**

```json
["server1", "server2", "server3"]
```

**Nested with json_path and value_field:**

```json
{
  "data": {
    "items": [
      { "hostname": "web-01", "ip": "10.0.1.1" },
      { "hostname": "web-02", "ip": "10.0.1.2" }
    ]
  }
}
```

With `json_path: "data.items"` and `value_field: "hostname"`, this returns
`["web-01", "web-02"]`.

---

## Source: Jinja2 Template

Evaluate a Jinja2 expression that outputs a JSON array.

```json
{
  "enabled": true,
  "source_type": "jinja2",
  "template": "{{ groups | tojson }}",
  "cache_ttl": 60
}
```

### Available Context Variables

| Variable | Type      | Description                               |
| -------- | --------- | ----------------------------------------- |
| `hosts`  | list[str] | Host names from the template's inventory  |
| `groups` | list[str] | Group names from the template's inventory |

The template **must output a valid JSON array**.

### Examples

```jinja2
{# List all hosts #}
{{ hosts | tojson }}

{# Filter hosts by prefix #}
{{ hosts | select("match", "^web") | list | tojson }}

{# Static list generated from range #}
{{ range(1, 11) | list | tojson }}
```

---

## API: Resolve Dynamic Choices

### Endpoint

```
POST /api/v2/job_templates/{id}/survey_spec/dynamic_choices/
```

### Permission

Requires `start` permission on the job template (same as launching).

### Request Body

```json
{
  "variables": ["target_host", "environment"]
}
```

- `variables` (optional): List of survey variable names to resolve.
  If omitted, resolves all dynamic choice questions.

### Response

```json
{
  "target_host": {
    "choices": ["web-01", "web-02", "db-01"],
    "source_type": "db_query"
  },
  "environment": {
    "choices": ["staging", "production"],
    "source_type": "api_endpoint"
  }
}
```

---

## Validation Rules

1. `dynamic_choices` is only valid on `multiplechoice` and `multiselect` types
2. When `dynamic_choices.enabled` is `true`, static `choices` field is not required
3. During job launch, answers to dynamic choice questions skip static choice validation
4. The `source_type` must be one of: `db_query`, `api_endpoint`, `jinja2`
5. DB query `model` must be from the allowed list
6. DB query `field` must be from: `name`, `id`, `description`
7. API endpoint requires a non-empty `url`
8. Jinja2 requires a non-empty `template`
9. `cache_ttl` must be a non-negative integer

---

## Frontend Behavior

1. When the Launch Dialog opens, it detects survey questions with `dynamic_choices.enabled`
2. A `POST` request is sent to the `dynamic_choices/` endpoint to resolve choices
3. Dropdown shows a loading spinner while choices are being fetched
4. A refresh button allows re-fetching choices on demand
5. The `dynamic` badge is displayed on questions with dynamic choices in both the
   survey editor and the launch dialog
6. The survey editor provides a UI to configure dynamic choices sources

---

## Caching

- Resolved choices are cached in Django's cache backend (Redis)
- Cache key includes the variable name and full source configuration hash
- Default TTL: 60 seconds
- Set `cache_ttl: 0` to disable caching
- Cache is shared across all users and launch requests

---

## Limitations

- Maximum 500 choices returned per question (to prevent UI issues)
- Jinja2 templates run in a restricted sandbox (no file I/O)
- External API requests have a configurable timeout (default 10s)
- DB query filters are limited to safe field lookups for security
