# 02 — Backend (Django)

Overview of backend modules — what each part does, where to find things, and what to watch out for.

---

## Django Applications

| App             | Path             | Responsibility                                     |
| --------------- | ---------------- | -------------------------------------------------- |
| `forail.main`    | `forail/main/`    | Core: models, tasks, signals, migrations, commands |
| `forail.api`     | `forail/api/`     | REST API: views, serializers, URL routing          |
| `forail.conf`    | `forail/conf/`    | Database-backed settings system                    |
| `forail.sso`     | `forail/sso/`     | SSO authentication (LDAP, SAML, social)            |
| `forail.ui_next` | `forail/ui_next/` | React frontend (served through Django)             |

---

## Models — Where things live

All models are in `forail/main/models/`. Each file covers one domain area:

| File                        | Contents                                                                           | Note                                                                                                                                                                                                                                                                                                                                                             |
| --------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `base.py`                   | Base classes for all models                                                        | `PrimordialModel` adds `created_by`, `modified_by` — every model has these                                                                                                                                                                                                                                                                                       |
| `organization.py`           | Organization, Team, Profile                                                        | Organization is the top-level container — **everything** belongs to one                                                                                                                                                                                                                                                                                          |
| `unified_jobs.py`           | UnifiedJobTemplate, UnifiedJob                                                     | Abstract base for ALL job types — key to understanding the system                                                                                                                                                                                                                                                                                                |
| `jobs.py`                   | JobTemplate, Job, JobHostSummary                                                   | Template defines "what to run", Job is "one execution of it"                                                                                                                                                                                                                                                                                                     |
| `inventory.py`              | Inventory, Host, Group, InventorySource                                            | Host/Group hierarchy, cloud sync sources                                                                                                                                                                                                                                                                                                                         |
| `projects.py`               | Project, ProjectUpdate                                                             | Git repository with playbooks                                                                                                                                                                                                                                                                                                                                    |
| `credentials/`              | Credential, CredentialType                                                         | Encrypted secrets — **never** plaintext in the database                                                                                                                                                                                                                                                                                                          |
| `workflow.py`               | WorkflowJobTemplate, nodes                                                         | DAG orchestration — success/failure/always branches                                                                                                                                                                                                                                                                                                              |
| `ha.py`                     | Instance, InstanceGroup                                                            | Cluster nodes and capacity                                                                                                                                                                                                                                                                                                                                       |
| `events.py`                 | JobEvent (and variants)                                                            | Output for every job — **partitioned table**                                                                                                                                                                                                                                                                                                                     |
| `notifications.py`          | NotificationTemplate                                                               | Email, Slack, webhook, PagerDuty...                                                                                                                                                                                                                                                                                                                              |
| `schedules.py`              | Schedule                                                                           | iCal recurrence rules for automatic execution                                                                                                                                                                                                                                                                                                                    |
| `activity_stream.py`        | ActivityStream                                                                     | Audit log of all changes                                                                                                                                                                                                                                                                                                                                         |
| `mixins.py`                 | SurveyJobTemplateMixin                                                             | Survey system — static and dynamic choices (see `docs/13-dynamic-surveys.md`)                                                                                                                                                                                                                                                                                    |
| `audit.py`                  | AuditEvent                                                                         | Immutable security audit log — credential access, auth, permissions (see `docs/14-audit-trail.md`)                                                                                                                                                                                                                                                               |
| `eda.py`                    | EventRule, EventLog, OutboundWebhook                                               | Event-Driven Automation — webhook rules, condition engine, outbound hooks (see `docs/15-event-driven-automation.md`)                                                                                                                                                                                                                                             |
| `drift.py`                  | HostFactSnapshot, DriftDetection, DriftAlertRule, DriftAlert                       | Drift Detection — fact snapshots, change tracking, alert rules (see `docs/16-drift-detection.md`)                                                                                                                                                                                                                                                                |
| `service_catalog.py`        | ServiceCatalogItem, ServiceRequest                                                 | Self-Service Portal — curated catalog wrapping JT/WFJT, request lifecycle with optional approval (see `docs/17-self-service-portal.md`)                                                                                                                                                                                                                          |
| `webauthn.py`               | WebAuthnCredential, WebAuthnRegistrationChallenge, WebAuthnAuthenticationChallenge | FIDO2 / WebAuthn — passwordless and second-factor authentication (see `docs/18-oidc-webauthn.md`)                                                                                                                                                                                                                                                                |
| `policy.py`                 | Policy, PolicyDecision                                                             | Policy-as-Code (OPA) — Rego rules evaluated before every launch (see `docs/19-policy-as-code.md`)                                                                                                                                                                                                                                                                |
| `scanner.py`                | Scanner, ScanResult, ScanFinding                                                   | IaC scanning & supply chain security — ansible-lint / checkov / pip-audit run before every launch (see `docs/20-iac-scanning.md`). Companion package: `forail/main/scanning/` (runner + tool adapters).                                                                                                                                                           |
| `observability/`            | (package, no ORM models)                                                           | OpenTelemetry bootstrap + helpers + tracing seams + metric handles + collector health probe. Initialized from `forail/asgi.py` / `forail/wsgi.py` / Celery boot. See `docs/21-observability.md`.                                                                                                                                                                   |
| `tenancy.py`                | TenantUsage, TenantQuotaEvent, TenantIsolationEvent                                | Multi-tenancy v1 — per-tenant quotas, branding, and cross-tenant audit layered on top of Organization. Companion package: `forail/main/tenancy/` (pure helpers, quota gate, provisioning, branding lookup, usage reconciliation, isolation middleware). Quota gate runs **before** Policy-as-Code and IaC Scanning at job launch. See `docs/22-multi-tenancy.md`. |
| `rbac.py`                   | Role                                                                               | RBAC system — roles and permissions                                                                                                                                                                                                                                                                                                                              |
| `oauth.py`                  | OAuth2Application, Token                                                           | API tokens                                                                                                                                                                                                                                                                                                                                                       |
| `execution_environments.py` | ExecutionEnvironment                                                               | Container image reference for execution                                                                                                                                                                                                                                                                                                                          |

### Watch out

- **UnifiedJob pattern:** Every executable (JobTemplate, Project, InventorySource) follows
  the same pattern — a template creates an instance. If you understand `UnifiedJobTemplate → UnifiedJob`,
  you understand all job types.

- **Credential encryption:** Fields marked as `secret` in `CredentialType.inputs` are
  encrypted before saving. Never read credentials directly from the database — use the API.

- **Computed fields on Inventory:** `total_hosts`, `hosts_with_active_failures`, etc.
  are updated via signals. If you add a host directly to the database (not through the API),
  these fields won't update until `update_computed_fields()` is called.

- **Organization is required:** Almost every resource requires an `organization` FK. Without
  an organization, RBAC won't work because roles are inherited from the organization.

---

## REST API — Structure

The API is in `forail/api/` and follows DRF (Django REST Framework) conventions.

### File locations

| What you're looking for             | Where to find it                                         |
| ----------------------------------- | -------------------------------------------------------- |
| API endpoints (URL routing)         | `forail/api/urls/` — one file per resource                |
| View logic (what the endpoint does) | `forail/api/views/` — one file per resource               |
| Serialization (JSON ↔ Model)        | `forail/api/serializers/` — data transformation           |
| Permissions                         | `forail/api/permissions.py` — access checks               |
| Authentication                      | `forail/api/authentication.py` — session, token, basic    |
| Pagination                          | `forail/api/pagination.py` — default 25 per page          |
| Filtering                           | `forail/api/filters.py` — search, ordering, field filters |

### API conventions

- **List:** `GET /api/v2/{resource}/` → paginated JSON with `count`, `next`, `previous`, `results`
- **Detail:** `GET /api/v2/{resource}/{id}/` → single object
- **Create:** `POST /api/v2/{resource}/` → body with data
- **Update:** `PATCH /api/v2/{resource}/{id}/` → partial update
- **Delete:** `DELETE /api/v2/{resource}/{id}/` → 204 No Content
- **Actions:** `POST /api/v2/{resource}/{id}/{action}/` → launch, cancel, update...
- **Nested:** `GET /api/v2/{parent}/{id}/{child}/` → related resources

### Watch out

- **`related` field:** Every API response has a `related` dict with URLs to related
  resources. Use this instead of manually constructing URLs.

- **`summary_fields`:** Inline data about related objects (organization name, project name...).
  This eliminates the need for additional API calls.

- **OPTIONS request:** Every endpoint returns metadata about available fields and actions
  via OPTIONS. Useful for dynamically generating forms.

- **RBAC filtering:** List endpoints automatically filter results based on user permissions.
  An admin sees everything; a regular user sees only what they have access to.

---

## Signals — Automatic side-effect actions

Signals are in `forail/main/signals.py` and automatically react to database changes:

| Signal                  | What it does                               |
| ----------------------- | ------------------------------------------ |
| Post-save on any model  | Creates a record in the Activity Stream    |
| Host create/delete      | Updates computed fields on the Inventory   |
| User change (superuser) | Synchronizes the system_administrator role |
| Group deletion          | Moves child groups and hosts to the parent |
| Workflow changes        | Updates approval template lifecycle        |

**Watch out:** Signals execute synchronously — if a signal throws an exception,
the entire transaction is rolled back. If you see unexpected IntegrityError,
check if a signal is attempting something invalid.

---

## Management Commands

Commands are in `forail/main/management/commands/`. They are run with `forail-manage`
(or `awx-manage` — both work, backward compatibility).

### Most important commands

**Instance management:**

- `forail-manage provision_instance --hostname=node1` — register a new cluster node
- `forail-manage deprovision_instance --hostname=node1` — remove a node
- `forail-manage list_instances` — show all nodes with capacity

**Users:**

- `forail-manage createsuperuser` — create admin user
- `forail-manage update_password --username=admin --password=new` — reset password

**Database:**

- `forail-manage migrate` — apply migrations
- `forail-manage check_db` — verify database connectivity
- `forail-manage dbshell` — open PostgreSQL shell

**Cleanup (run periodically):**

- `forail-manage cleanup_jobs --days=90` — delete old jobs and events
- `forail-manage cleanup_sessions` — delete expired sessions
- `forail-manage cleanup_tokens` — delete expired OAuth tokens

**Diagnostics:**

- `forail-manage check_instance_ready` — is the node ready for work
- `forail-manage stats` — system statistics

### Watch out

- `cleanup_jobs` is **critical** for production. Without it, the job event table grows
  without limit. Recommendation: set up as a System Job that runs daily.

- `provision_instance` is automatically called in the init script during deployment.
  You only run it manually when adding new nodes to the cluster.

---

## Configuration System — Two levels

### Level 1: File-based (Django settings)

Loaded at startup, cannot be changed without restart.

| File                                      | Contents                                        |
| ----------------------------------------- | ----------------------------------------------- |
| `forail/settings/defaults/base.py`         | Core: DATABASES, INSTALLED_APPS, REST_FRAMEWORK |
| `forail/settings/defaults/auth.py`         | Authentication backends                         |
| `forail/settings/defaults/jobs.py`         | Job execution defaults                          |
| `forail/settings/defaults/celery_conf.py`  | Celery/Redis configuration                      |
| `forail/settings/defaults/logging_conf.py` | Logging                                         |
| `forail/settings/production.py`            | Production overrides (DEBUG=False)              |
| `/etc/tower/conf.d/*.py`                  | Per-module settings inside the container        |

### Level 2: Database-backed (Forail conf system)

Stored in PostgreSQL, changed via API (`/api/v2/settings/`) **without restart**.

Registered in `forail/conf/` and covering: job timeouts, LDAP configuration,
logging, notifications, and much more.

**Watch out:** Database settings **override** file settings. If something isn't
working as expected, check if it's been overridden in the database:

```bash
forail-manage print_setting SETTING_NAME
```

---

## Migrations

Forail has **252 Django migrations** in `forail/main/migrations/`.

### Watch out

- All migrations reference `forail.main.fields` — not `awx.main.fields`. If you
  create a new migration, `makemigrations` will automatically use the correct prefix.

- **Never edit existing migrations** — only add new ones.

- If a migration fails, check `forail-manage showmigrations | grep "\[ \]"`
  to see which ones are unapplied.

- The init script automatically runs `migrate` during deployment.
