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
| ~~Jinja2 Template~~ | **Withdrawn** — see below                          | —                                   |

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
| `source_type` | string  | Yes (if enabled) | One of: `db_query`, `api_endpoint` (`jinja2` is withdrawn) |
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

Fetch choices from an HTTPS endpoint. Supports JSON responses.

> **The destination must be named by an administrator.** The server makes this
> request from inside the cluster, and the URL comes from the survey — so
> without a destination policy, whoever can edit a job template can point the
> server at cloud metadata, at a service bound to loopback, or at a neighbouring
> pod, and read the reply through the choices endpoint. Hosts are therefore
> listed in `SURVEY_DYNAMIC_CHOICES_API_ALLOWLIST` in the server settings file,
> matched exactly. The list is **empty by default, which disables this source
> type**.
>
> ```python
> # /etc/tower/conf.d/dynamic_surveys.py
> SURVEY_DYNAMIC_CHOICES_API_ALLOWLIST = ['cmdb.internal.example.com']
> ```
>
> Rules that apply even to a listed host:
>
> - **HTTPS only.**
> - The name is re-checked **after DNS resolution**. Private addresses are
>   allowed — an on-prem CMDB on `10.0.0.0/8` is the ordinary case — but
>   loopback, link-local (`169.254.0.0/16`, where cloud metadata lives),
>   multicast and reserved addresses are refused. A listed name whose DNS answer
>   points inward does not get through.
> - **Redirects are never followed.** The first hop is the one that was checked;
>   every hop after it would be the peer's choice.
> - Methods are limited to `GET` and `POST`, `timeout` is capped at 30 seconds,
>   and the response is read up to 1 MiB.
>
> A URL that is not permitted is rejected when the survey is **saved**, so the
> editor is told rather than left with a question that silently resolves to
> nothing.

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
| `url`         | string  | —       | HTTPS endpoint URL (required, host must be allowlisted) |
| `method`      | string  | `GET`   | HTTP method (`GET` or `POST`)              |
| `headers`     | object  | `{}`    | Custom HTTP headers. **Stored in the survey spec in plaintext** — anyone who can read the job template can read them |
| `json_path`   | string  | `""`    | Dot-notation path to the array in response |
| `value_field` | string  | `""`    | Field to extract from objects in the array |
| `timeout`     | integer | `10`    | Request timeout in seconds (capped at 30)  |
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

## Source: Jinja2 Template — withdrawn

**This source type is disabled and surveys can no longer be saved with it.**

The template was rendered on the server, in the web process, whenever a user
with `start` permission opened the launch prompt. Jinja2 seeds every environment
with objects whose `__init__.__globals__` reaches Python's module table, so
whoever could edit a job template's survey could run arbitrary code as the web
process — `{{ cycler.__init__.__globals__.os.environ.get('PATH') }}` returned the
server's `PATH`. Earlier versions of this page claimed the templates ran in a
restricted sandbox. They did not.

Surveys already stored with `source_type: jinja2` resolve to **no choices** and
log a warning; they are not executed. Move them to `db_query` (for anything
drawn from inventory) or `api_endpoint` (for anything computed elsewhere).

An operator who accepts the risk can set
`SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED = True` in the server settings file — not
via `/api/v2/settings/`, deliberately, so the API used to store a template cannot
also enable its execution. Templates then render in a Jinja2 sandbox with globals
removed and a reduced filter set. Treat that as hardening, not as a boundary:
sandbox escapes are found periodically, and a template rendering in the web
process is worth an escape to whoever plants it.

```json
{
  "enabled": true,
  "source_type": "jinja2",
  "template": "{{ groups | sort | tojson }}",
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

{# `range` and the other Jinja globals are removed; build from context instead #}
{{ groups | sort | tojson }}
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
3. During job launch, an answer to a dynamic-choices question is checked against
   the **resolved** list, not against the static `choices` field. If the source
   cannot be resolved the list is empty and every answer is rejected — an answer
   that cannot be validated is not accepted
4. The `source_type` must be one of: `db_query`, `api_endpoint`. `jinja2` is
   rejected unless `SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED` is `True` in the
   server settings file
5. DB query `model` must be from the allowed list
6. DB query `field` must be from: `name`, `id`, `description`
7. API endpoint requires a non-empty `url`
8. Jinja2, where an operator has re-enabled it, requires a non-empty `template`
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
- The cache key covers the question, the source configuration, **and the scope
  the answer was resolved in** — job template, organization and inventory. It
  used to be the variable name plus a config hash alone, so two templates with
  the same question and different inventories shared one entry and the second
  caller was served the first one's host names
- Nothing is cached when there is no template to scope by
- Default TTL: 60 seconds
- Set `cache_ttl: 0` to disable caching
- Within one scope, the cache is shared across users

---

## Limitations

- Maximum 500 choices returned per question (to prevent UI issues), applied to
  every source type
- Jinja2 as a source type is withdrawn; where an operator has re-enabled it,
  templates render in a Jinja2 sandbox with globals removed and a reduced filter
  set — hardening, not a trust boundary
- External API requests have a configurable timeout (default 10s)
- DB query filters are limited to safe field lookups for security
