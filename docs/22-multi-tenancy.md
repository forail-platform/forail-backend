# 22 — Multi-Tenancy (v1)

**Tier 3.2 — DONE**

Forge Platform supports **soft multi-tenancy**: a single Forge install can host
many customer tenants, each with its own quotas, branding, and an admin team,
without spinning up separate databases or separate Celery workers. Tenancy is
layered on top of the existing Organization + RBAC primitives — no Postgres
row-level security, no per-tenant schemas.

Everything is additive and gated by a single kill switch (`TENANCY_ENABLED`).
With the switch off, all tenant hooks short-circuit and Forge behaves exactly
as before.

---

## Scope (v1)

**In:**

- Organization promoted to "Tenant" via 11 additive fields (no new Org model).
- Per-tenant quotas enforced at job launch: concurrent jobs, daily launches,
  host count, storage MB.
- Tenant branding (logo, colors, custom domain) served by a **public**
  `/api/v2/branding/` endpoint so the UI can skin itself before login.
- Tenant provisioning REST API (`POST /api/v2/tenants/`) that atomically
  creates an Organization, admin user, default team, and TenantUsage row.
- Quota audit log (`TenantQuotaEvent`) — one row per allow/block decision.
- Cross-tenant access audit (`TenantIsolationEvent`) — **audit only** in v1,
  no blocking.
- Celery beat reconciliation task that refreshes host count / storage usage.

**Out (deferred to v2):**

- Postgres row-level security policies
- Strict-mode enforcement (blocking cross-tenant queries)
- Per-tenant Celery queues
- Per-tenant API rate limiting (token bucket)
- Custom-domain TLS provisioning
- Billing / metering hooks

---

## Architecture

```
  POST /api/v2/job_templates/{id}/launch/
                │
                ▼
  ┌─────────────────────────────────────────┐
  │ forge.launch  (OTel span, Tier 3.6)      │
  │                                          │
  │   check_tenant_quota(job, request)  ◄── NEW  (Tier 3.2)
  │        │ allowed → inc counters         │
  │        │ blocked → 429 + QuotaEvent     │
  │        ▼                                │
  │   evaluate_launch(...)  (Policy-as-Code)│
  │        ▼                                │
  │   run_scanners_for_launch(...)          │
  │        ▼                                │
  │   job.signal_start()                    │
  └─────────────────────────────────────────┘
```

The quota gate is the **first** gate inside the launch span so that blocked
tenants never consume policy/scanning work. A post-finish signal decrements
`concurrent_jobs_count` so the counter stays honest.

---

## Models — `forge/main/models/tenancy.py`

### Organization (extended in place)

11 additive fields on the existing `Organization` model. All default to
`False` / `null` / empty string so existing orgs are untouched.

| Field                          | Type                    | Purpose |
|--------------------------------|-------------------------|---------|
| `is_tenant_root`               | BooleanField (False)    | Marks org as a tenant boundary |
| `tenant_max_concurrent_jobs`   | PositiveIntegerField ?  | Concurrent running jobs cap |
| `tenant_max_daily_launches`    | PositiveIntegerField ?  | Rolling daily launch cap |
| `tenant_max_hosts`             | PositiveIntegerField ?  | Host count cap |
| `tenant_max_storage_mb`        | PositiveIntegerField ?  | Project storage cap |
| `tenant_isolation_strict`      | BooleanField (False)    | Flip on → audit cross-tenant reads |
| `tenant_logo_url`              | CharField (blank)       | Branding logo |
| `tenant_primary_color`         | CharField (blank)       | Hex color (`#5B47E0`) |
| `tenant_secondary_color`       | CharField (blank)       | Hex color |
| `tenant_custom_domain`         | CharField (blank, idx)  | Hostname used by branding lookup |
| `tenant_contact_email`         | EmailField (blank)      | Primary contact |

`null` on any quota means **unlimited**.

### TenantUsage (new)

One row per tenant Org. The launch hook reads/writes
`concurrent_jobs_count` / `launches_today_count`; the beat task refreshes
`hosts_count` / `storage_mb_used`.

| Field                           | Type |
|---------------------------------|------|
| `organization`                  | OneToOneField(Organization, related_name='tenant_usage') |
| `concurrent_jobs_count`         | PositiveIntegerField (0) |
| `launches_today_count`          | PositiveIntegerField (0) |
| `launches_today_window_start`   | DateTimeField |
| `hosts_count`                   | PositiveIntegerField (0) |
| `storage_mb_used`               | PositiveIntegerField (0) |
| `last_recalculated_at`          | DateTimeField (null) |

### TenantQuotaEvent (new)

One row per quota decision. Mirrors `PolicyDecision` shape.

| Field                   | Type |
|-------------------------|------|
| `organization`          | FK Organization SET_NULL |
| `organization_name`     | CharField (cached — row survives org delete) |
| `quota_kind`            | choices=`concurrent_jobs` / `daily_launches` / `hosts` / `storage_mb` |
| `decision`              | choices=`allowed` / `blocked` |
| `current_value`         | PositiveIntegerField |
| `limit_value`           | PositiveIntegerField (null when unlimited) |
| `triggered_by`          | FK auth.User SET_NULL |
| `unified_job_template`  | FK UnifiedJobTemplate SET_NULL |
| `message`               | TextField |

### TenantIsolationEvent (new)

One row per cross-tenant read observed when `tenant_isolation_strict=True`.

| Field                     | Type |
|---------------------------|------|
| `user`                    | FK auth.User SET_NULL |
| `user_organization`       | FK Organization SET_NULL |
| `accessed_organization`   | FK Organization SET_NULL |
| `resource_type`           | CharField |
| `resource_id`             | PositiveIntegerField (null) |
| `request_path`            | CharField |
| `blocked`                 | BooleanField (False — v1 audit only) |

---

## Pure helpers — `forge/main/tenancy/helpers.py`

Exported for standalone test; zero Django imports.

```python
def check_quota_value(current: int, limit: int | None) -> bool: ...
def is_window_expired(window_start: datetime, now: datetime) -> bool: ...
def reset_daily_window(now: datetime) -> tuple[datetime, int]: ...
def format_quota_message(kind: str, current: int, limit: int | None) -> str: ...
def normalize_branding_host(host: str) -> str: ...  # lowercase + strip port
def validate_hex_color(value: str) -> bool: ...
```

All four quota kinds use `check_quota_value` so the semantics are identical
(`None` → unlimited; `current >= limit` → blocked).

---

## Tenancy package layout — `forge/main/tenancy/`

| Module            | Role |
|-------------------|------|
| `__init__.py`     | Re-exports the public surface |
| `helpers.py`      | Pure functions (standalone-testable) |
| `quota.py`        | `QuotaResult`, `check_tenant_quota(job, request)`, `on_job_finished(job)` |
| `provisioning.py` | `provision_tenant(payload)` — atomic Org + User + Team + Usage |
| `branding.py`     | `get_branding_for_host(host) -> dict | None` |
| `usage.py`        | `recalculate_tenant_usage(org)` — drift reconciliation |
| `isolation.py`    | `TenantIsolationMiddleware` — cross-tenant audit (v1 log only) |

---

## Launch hook order

In `forge/api/views/job_templates.py`, `workflows.py`, and `ad_hoc_commands.py`,
the launch sequence inside the `forge.launch` OTel span is:

```
check_tenant_quota   (NEW — Tier 3.2)   — 429 on block
evaluate_launch      (Tier 2.2)         — 403 on block
run_scanners_for_launch (Tier 3.4)      — 403 on block
job.signal_start()
```

The quota gate sets `quota_blocked=<kind>` on the current span for easy
trace filtering.

### Job-finished signal

`forge.main.signals.handlers` dispatches `on_job_finished(job)` on each
`unified_job_finished` signal, which atomically decrements
`concurrent_jobs_count` for the tenant. The Celery reconciliation task also
corrects drift (`concurrent_jobs_count = actual running UnifiedJob count`)
on every tick.

---

## Settings — `forge/main/conf.py`

| Key                                   | Default | Notes |
|---------------------------------------|---------|-------|
| `TENANCY_ENABLED`                     | `False` | Kill switch — all gates short-circuit when off |
| `TENANCY_DEFAULT_MAX_CONCURRENT_JOBS` | `0`     | `0` = unlimited |
| `TENANCY_DEFAULT_MAX_DAILY_LAUNCHES`  | `0`     | `0` = unlimited |
| `TENANCY_QUOTA_RECALC_INTERVAL_S`     | `300`   | Beat task period |

All four live under the **System** category and show up in
`/api/v2/settings/system/`.

---

## REST API

All `/api/v2/tenants/*` endpoints require `is_superuser`. `/api/v2/branding/`
is **public** (no auth classes).

| Method | Path                                       | Purpose |
|--------|--------------------------------------------|---------|
| GET    | `/api/v2/tenants/`                         | List tenant orgs with embedded usage + quota |
| POST   | `/api/v2/tenants/`                         | Provision a tenant (Org + admin + team + usage, all in one txn) |
| GET    | `/api/v2/tenants/{id}/`                    | Detail (nested usage, quota, branding) |
| PATCH  | `/api/v2/tenants/{id}/`                    | Update quotas / branding |
| DELETE | `/api/v2/tenants/{id}/?confirm=true`       | Wipe org + all its content (fails if running jobs > 0) |
| POST   | `/api/v2/tenants/{id}/recalculate/`        | Force usage recompute |
| GET    | `/api/v2/tenant_quota_events/`             | Audit log |
| GET    | `/api/v2/branding/?host=<hostname>`        | **PUBLIC** — tenant branding lookup, 404 on miss |

### Provisioning payload

```json
{
  "name": "Acme Corp",
  "admin_username": "acme-admin",
  "admin_email": "admin@acme.example",
  "admin_password": "...",
  "quota": {
    "max_concurrent_jobs": 10,
    "max_daily_launches": 500,
    "max_hosts": 200,
    "max_storage_mb": 5000
  },
  "branding": {
    "logo_url": "https://...",
    "primary_color": "#5B47E0",
    "custom_domain": "acme.forge.example"
  }
}
```

Idempotent on `name`: a POST with an existing tenant name returns the
existing tenant.

### Branding response

```json
{
  "tenant_id": 42,
  "name": "Acme Corp",
  "logo_url": "https://...",
  "primary_color": "#5B47E0",
  "secondary_color": "#3B2799"
}
```

---

## Standalone tests — `tests_standalone/test_tenancy.py`

Pure-helper tests (no Django setup). Covers:

- `check_quota_value` under/at/over limit, `None` unlimited
- `is_window_expired` under/over 24h boundary
- `reset_daily_window` returns top-of-UTC-day
- `format_quota_message` human-readable strings for each kind
- `QuotaResult` aggregation (any block → overall block)
- `normalize_branding_host` lowercase + strip port
- `validate_hex_color` valid/invalid patterns
- Provisioning payload validation (required fields, password strength, email)

Run:

```bash
python -m unittest tests_standalone.test_tenancy -v
```

---

## Verification (E2E smoke)

With the stack running:

1. Enable tenancy — `Settings → System → TENANCY_ENABLED = true`.
2. `POST /api/v2/tenants/` provisioning a fake "Acme" tenant with
   `custom_domain=acme.localhost`, `max_concurrent_jobs=1`.
3. Sidebar → **Tenancy → Tenants** → Acme appears with usage bars.
4. As `acme-admin`, launch two jobs back-to-back. Second returns **429** with
   `reasons=[concurrent_jobs:...]`; a `TenantQuotaEvent` row appears in the
   audit log.
5. `curl -sk 'https://localhost/api/v2/branding/?host=acme.localhost'` →
   returns Acme's branding JSON **without** an auth header.
6. Load `https://localhost` with `Host: acme.localhost` → UI skins with
   Acme colors and logo **before** login.
7. `POST /api/v2/tenants/{id}/recalculate/` → usage values refresh.
8. `DELETE /api/v2/tenants/{id}/?confirm=true` → tenant + all its resources
   removed.

---

## Files

- `forge/main/models/tenancy.py` — models
- `forge/main/models/organization.py` — extended in place
- `forge/main/migrations/0204_multi_tenancy.py` — schema migration
- `forge/main/tenancy/` — helpers + quota + provisioning + branding + usage + isolation
- `forge/main/tasks/tenancy.py` — Celery beat task
- `forge/main/conf.py` — settings registration
- `forge/api/serializers/tenancy.py`
- `forge/api/views/tenancy.py`
- `forge/api/urls/tenancy.py`
- `tests_standalone/test_tenancy.py`
