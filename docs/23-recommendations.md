# 23 — Recommendations Engine

**Tier 3.7 — NEW**

Forail Platform ships a **rule-based recommendations engine** that surfaces
actionable, scope-aware hints about platform health. Recommendations appear on
the Dashboard and inside each wizard, and are designed to nudge operators
toward best practices ("you have job templates but no IaC scanners",
"the admin user is still using the default password") without ever blocking
their work.

Everything is read-only and stateless. The engine has no Django models, no
migrations, and no DB tables of its own — it computes its results live from
existing tables, with a 60-second in-memory cache to keep the cost negligible.

---

## Scope (v1)

**In:**

- 12 built-in rules covering compliance, tenancy, observability, automation,
  self-service, access, and security.
- Single read-only HTTP endpoint: `GET /api/v2/recommendations/?scope=<scope>`.
- 8 scopes: `dashboard`, `automation`, `self_service`, `tenancy`, `compliance`,
  `resources`, `access`, `all`.
- 3 severity levels: `critical`, `warn`, `info` (sorted critical → info).
- 60-second in-memory cache to amortise the cost of context aggregation.
- Pure-Python module (no Django app) so the rules are unit-testable in
  isolation against a fake `RuleContext`.
- 17 standalone test classes covering every rule plus the evaluator.

**Out (deferred):**

- Persistent dismissals (today the UI dismisses locally only).
- Per-user / per-org filtering of which rules apply.
- Custom user-defined rules.
- Webhook delivery of new criticals.
- Persistent recommendation history / metrics.

---

## Module Layout

```
forail/main/recommendations/
├── __init__.py        # public exports: build_context, evaluate, Recommendation
├── types.py           # @dataclass RuleContext, Recommendation
├── rules.py           # 12 pure rule functions
└── engine.py          # build_context() + evaluate() + 60s cache

forail/api/
├── views/recommendations.py        # RecommendationsList APIView
├── serializers/recommendations.py  # RecommendationSerializer
└── urls/recommendations.py         # urlpatterns

tests_standalone/
└── test_recommendations.py         # 17 test classes
```

The module is **not** a Django app — it has no `apps.py`, no `models.py`, no
migrations, and is **not** registered in `INSTALLED_APPS`. Its URL include is
wired directly from `forail/api/urls/urls.py`.

---

## Data Types

### `RuleContext`

A frozen aggregation of everything the rules need. Built once per request (or
once per minute when the cache is warm) by `build_context()`, which runs
defensive lazy queries against the existing tables.

| Field                    | Type                      | Source                                                      |
| ------------------------ | ------------------------- | ----------------------------------------------------------- |
| `scanners_enabled_count` | `int`                     | `Scanner.objects.filter(enabled=True).count()`              |
| `policies_total`         | `int`                     | `Policy.objects.count()`                                    |
| `policies_enforce_count` | `int`                     | `Policy.objects.filter(mode='enforce').count()`             |
| `organizations_total`    | `int`                     | `Organization.objects.count()`                              |
| `tenancy_enabled`        | `bool`                    | `settings.TENANCY_ENABLED`                                  |
| `otel_enabled`           | `bool`                    | `settings.OTEL_ENABLED`                                     |
| `job_templates_total`    | `int`                     | `JobTemplate.objects.count()`                               |
| `schedules_total`        | `int`                     | `Schedule.objects.count()`                                  |
| `catalog_items_total`    | `int`                     | `CatalogItem.objects.count()`                               |
| `surveys_total`          | `int`                     | `JobTemplate.objects.exclude(survey_spec=None).count()`     |
| `drift_detections_total` | `int`                     | `DriftDetection.objects.count()`                            |
| `projects`               | `list[(name, last_sync)]` | `Project.objects.values_list('name', 'last_update_failed')` |
| `tenant_usage`           | `list[(name, quota_pct)]` | `TenantUsage` aggregate                                     |
| `teams_count`            | `int`                     | `Team.objects.count()`                                      |
| `admin_default_password` | `bool`                    | `User.check_password('password')` for admin                 |

Each query is wrapped in `try/except` so a missing table (e.g. recommendations
on a fresh install before migrations finish) returns a zero/false value instead
of crashing.

### `Recommendation`

```python
@dataclass(frozen=True)
class Recommendation:
    id: str           # unique stable id, e.g. 'no_scanners'
    scope: str        # one of the 8 scopes
    severity: str     # 'critical' | 'warn' | 'info'
    title: str        # human title
    why: str          # human explanation, 1–2 sentences
    action_link: str  # frontend route the UI button should open
```

---

## The 12 Rules

| ID                       | Scope          | Severity     | Triggers when…                                            |
| ------------------------ | -------------- | ------------ | --------------------------------------------------------- |
| `default_admin_password` | `dashboard`    | **critical** | The bootstrap `admin` user still has the seed password    |
| `no_scanners`            | `compliance`   | warn         | At least one job template exists but no enabled scanners  |
| `multi_org_no_tenancy`   | `tenancy`      | warn         | More than one Organization but `TENANCY_ENABLED=False`    |
| `tenant_near_quota`      | `tenancy`      | warn         | Any tenant is using > 80% of any quota                    |
| `all_policies_warn`      | `compliance`   | info         | At least one policy exists but none are in `enforce` mode |
| `no_observability`       | `dashboard`    | info         | `OTEL_ENABLED=False`                                      |
| `stale_project`          | `automation`   | info         | Any Project has not synced in 14+ days                    |
| `no_schedules`           | `automation`   | info         | Job templates exist but no Schedules are configured       |
| `no_drift`               | `compliance`   | info         | Job templates exist but no DriftDetections configured     |
| `few_surveys`            | `self_service` | info         | Less than 50% of templates expose a survey                |
| `no_catalog_items`       | `self_service` | info         | Job templates exist but the Service Catalog is empty      |
| `only_default_team`      | `access`       | info         | Only the seed Team exists                                 |

Each rule is a pure function `(ctx: RuleContext) -> Recommendation | None`.
A rule that raises an exception is silently dropped — the engine never returns
a partial error to the API.

---

## HTTP API

### `GET /api/v2/recommendations/`

**Auth:** `IsAuthenticated` (any logged-in user can read).

**Query parameters**

| Name    | Type  | Default | Description                                                                                                               |
| ------- | ----- | ------- | ------------------------------------------------------------------------------------------------------------------------- |
| `scope` | `str` | `all`   | Filter by scope. One of: `all`, `dashboard`, `automation`, `self_service`, `tenancy`, `compliance`, `resources`, `access` |

**Response 200**

```json
{
  "count": 3,
  "results": [
    {
      "id": "default_admin_password",
      "scope": "dashboard",
      "severity": "critical",
      "title": "Default admin password in use",
      "why": "The admin user is still using the default password. Change it immediately to secure your installation.",
      "action_link": "/users"
    },
    {
      "id": "multi_org_no_tenancy",
      "scope": "tenancy",
      "severity": "warn",
      "title": "Multiple organizations without tenancy",
      "why": "You have more than one organization but tenancy is disabled. Enable tenancy to enforce quotas and isolation.",
      "action_link": "/wizards/tenancy"
    },
    {
      "id": "no_observability",
      "scope": "dashboard",
      "severity": "info",
      "title": "Observability is not enabled",
      "why": "OpenTelemetry exporters are off. Enable them to get traces, metrics, and logs flowing to your backend.",
      "action_link": "/wizards/observability"
    }
  ]
}
```

Results are always sorted **critical → warn → info**, with stable ordering
inside each severity bucket (the order in which the rule is registered).

### Examples

**All recommendations**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  https://forail.example.com/api/v2/recommendations/
```

**Only compliance**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://forail.example.com/api/v2/recommendations/?scope=compliance"
```

```json
{
  "count": 1,
  "results": [
    {
      "id": "no_scanners",
      "scope": "compliance",
      "severity": "warn",
      "title": "No IaC scanners configured",
      "why": "You have job templates but no IaC scanners. Enable scanning to catch unsafe playbooks before they run.",
      "action_link": "/wizards/compliance"
    }
  ]
}
```

**Only tenancy**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://forail.example.com/api/v2/recommendations/?scope=tenancy"
```

```json
{
  "count": 2,
  "results": [
    {
      "id": "multi_org_no_tenancy",
      "scope": "tenancy",
      "severity": "warn",
      "title": "Multiple organizations without tenancy",
      "why": "You have more than one organization but tenancy is disabled. Enable tenancy to enforce quotas and isolation.",
      "action_link": "/wizards/tenancy"
    },
    {
      "id": "tenant_near_quota",
      "scope": "tenancy",
      "severity": "warn",
      "title": "Tenant near concurrent-job quota",
      "why": "Tenant \"production-1\" is using 92% of its concurrent job limit. Consider raising the quota.",
      "action_link": "/tenants"
    }
  ]
}
```

**Empty result**

When nothing matches (best case — your platform is healthy), the API returns:

```json
{ "count": 0, "results": [] }
```

---

## Caching

`build_context()` is wrapped in a 60-second TTL memoizer. The cache key is
constant (process-local), so:

- The first request after a cold start pays the full DB cost (~10–15 ms with
  realistic data).
- Subsequent requests within 60 s are essentially free (microseconds).
- The cache is per-process; in a multi-worker uWSGI deployment each worker
  warms its own cache.

This is intentional. There is no cross-process invalidation because
recommendations are not load-bearing — being 60 s stale is fine.

To bypass the cache (for tests), call `build_context(_cache_bust=True)`.

---

## Severity → UI Mapping

The frontend uses these conventions; rules should pick severity to match the
intended urgency.

| Severity   | When to use                                  | UI treatment                                        |
| ---------- | -------------------------------------------- | --------------------------------------------------- |
| `critical` | Active security or data-loss risk            | Red badge, stays at the top, never auto-dismissable |
| `warn`     | Best-practice violation that will bite later | Amber badge, dismissible per session                |
| `info`     | Tip or suggestion                            | Blue badge, dismissible per session                 |

Today only `default_admin_password` is `critical`. Adding new criticals should
require explicit review — they cannot be silenced from the UI.

---

## Frontend Integration

The frontend hits the endpoint via TanStack Query in
`src/api/hooks/useRecommendations.ts`. Two consumers:

1. **Dashboard banner** (`src/pages/Dashboard.tsx`) — calls
   `useRecommendations('dashboard')`, displays the top 5 in a Getting Started
   card and groups the rest by severity.
2. **Wizard panel** (`src/components/wizard/RecommendationsPanel.tsx`) — every
   wizard renders this panel at the top of its content area, scoped to that
   wizard's domain (e.g. `useRecommendations('compliance')` inside the
   ComplianceWizard).

Both consumers refetch every 60 seconds via TanStack's `refetchInterval`,
matching the backend cache TTL.

---

## Adding a New Rule

1. Edit `forail/main/recommendations/rules.py`. Add a function:

   ```python
   def rule_my_new_check(ctx: RuleContext) -> Recommendation | None:
       if not <my condition>:
           return None
       return Recommendation(
           id='my_new_check',
           scope='compliance',
           severity='warn',
           title='Short, action-oriented title',
           why='One or two sentences explaining why this matters.',
           action_link='/wherever',
       )
   ```

2. Register it in the `ALL_RULES` list at the bottom of the same file.
3. If your rule needs new context data, add a field to `RuleContext` in
   `types.py` and populate it in `engine.build_context()`.
4. Add a unit test in `tests_standalone/test_recommendations.py`. At minimum
   cover **trigger** and **non-trigger** cases.
5. Run the tests:

   ```bash
   pytest tests_standalone/test_recommendations.py -v
   ```

6. (Optional) add an `i18n` key on the frontend if the title/why should be
   translated rather than served verbatim.

---

## Testing

Standalone (no Django):

```bash
pytest tests_standalone/test_recommendations.py
```

The 17 test classes cover every rule plus the evaluator (severity sort, scope
filter, exception swallowing, empty context). Because the rules take a plain
dataclass, no fixtures, no DB, no Django setup is required — the entire suite
runs in well under a second.

---

## Operational Notes

- **Cost:** ~10 ms cold, microseconds warm. Safe to call every page load.
- **Failure mode:** the endpoint never 500s on rule errors — failed rules are
  dropped, working rules still return.
- **Permissions:** any authenticated user. There is intentionally no per-user
  filtering — recommendations describe platform-wide state.
- **Telemetry:** the endpoint emits an OpenTelemetry span
  (`recommendations.evaluate`) with `scope` and `count` attributes when OTel
  is enabled (see [21 — Observability](21-observability.md)).
- **Disable globally:** there is no kill switch in v1. If you need to hide the
  feature, add `DISABLE_RECOMMENDATIONS=True` to settings and short-circuit
  the view — out of scope for v1.

---

## Roadmap

- **v1.1** — persistent dismissals (`POST /api/v2/recommendations/<id>/dismiss/`)
- **v1.2** — user-defined rules via Rego or YAML DSL
- **v1.3** — webhook delivery of new criticals
- **v1.4** — recommendation history with timestamps for trending

---

## See Also

- [16 — Drift Detection](16-drift-detection.md) — feeds `no_drift` and adjacent rules
- [19 — Policy-as-Code](19-policy-as-code.md) — feeds `all_policies_warn`
- [20 — IaC Scanning](20-iac-scanning.md) — feeds `no_scanners`
- [22 — Multi-Tenancy](22-multi-tenancy.md) — feeds `multi_org_no_tenancy`, `tenant_near_quota`
- [User Handbook → Dashboard](../../forail-deploy/docs/HANDBOOK.md#dashboard) — where the UI surfaces these
