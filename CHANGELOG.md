# Changelog

All notable changes to the Forail Backend will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to CalVer (`YYYY.MM.PATCH`).

## [Unreleased]

## [2026.07.1] - 2026-07-26

### Fixed
- **The task pod stopped resetting how jobs are executed on every start.** Its
  Kubernetes self-registration hardcoded `node_type='control'` and re-registered
  the `default` queue as a ContainerGroup, and both calls overwrite what is
  already in the database — so every restart, eviction and rolling upgrade undid
  whatever the installer had configured. Upgrading from 2026.06.0 left the
  `default` group without an execution-capable member, and every launch then sat
  in `pending` with only *"not enough available capacity"* to explain it.
  Registration now takes its intent from `FORAIL_NODE_TYPE`, which the Helm chart
  and the Compose stack already set, and derives the default queue from it: an
  execution-capable pod gets a regular instance group containing itself, a
  control-only pod keeps the ContainerGroup. Both defaults are unchanged when the
  variable is unset.

## [2026.07.0] - 2026-07-25

### Added
- **AWX → Forail migration importer** (`forail-manage import_from_awx`): a
  one-shot, idempotent importer that pulls Organizations, Users, Teams,
  Credential Types, Credentials, Projects, Inventories (groups + hierarchy +
  hosts) and Job Templates from an existing AWX/AAP install via its REST API.
  Supports `--dry-run`, `--resource` filtering, token or basic auth, and
  `--insecure`. Secret credential inputs are not exported by AWX, so the
  importer reports how many secret fields must be re-entered. (Workflows,
  schedules, notification templates, inventory sources and RBAC role
  assignments are planned follow-ups.)

### Security
- **Audit superuser grant/revoke** to the dedicated `AuditEvent` log
  (`log_permission_change`), independently of the activity stream (which can be
  disabled) — privilege changes are now always captured.
- **Hash `actor_session_id`** in audit records (SHA-256) instead of storing the
  raw Django session key, so audit-log readers cannot hijack live sessions.
- **Trusted-proxy `X-Forwarded-For`**: the audit `actor_ip` now honors
  `X-Forwarded-For` only when the direct peer is in `PROXY_IP_ALLOWED_LIST`,
  preventing source-IP spoofing.
- **Censor OAuth `refresh_token`** (in addition to `token`) in activity-stream
  create and delete entries.
- **Fail loud on tenant quota errors**: the per-tenant concurrency-quota
  decrement is no longer swallowed by a bare `except` — failures are logged.
- **BREAKING — enforce SAML signing + SHA-256 by default**:
  `SOCIAL_AUTH_SAML_SECURITY_CONFIG` now defaults to `wantMessagesSigned` /
  `wantAssertionsSigned`, replay protection, and `rsa-sha256` / `sha256`.
  IdPs sending unsigned or SHA-1 assertions must be reconfigured (or the setting
  relaxed). See the 2026.07 release notes for upgrade guidance.
- **BREAKING — SAML role attribute requires a value**: granting
  `is_superuser` / `is_system_auditor` from a SAML attribute now requires a
  non-empty `is_*_value`; configuring only `is_*_attr` no longer escalates every
  user presenting the attribute (fails safe + warns).
- Removed dead, unregistered `ForailOIDCAuth` backend to avoid implying a second
  active OIDC backend. OIDC is handled by `social_core`'s `OpenIdConnectAuth`,
  whose requests honor `SOCIAL_AUTH_OIDC_VERIFY_SSL` (verified).
- **Tenant isolation fails closed**: the RLS middleware now aborts a request
  (HTTP 500) if it cannot install the tenant scope, instead of proceeding with
  global row visibility. The strict-isolation gate resolves the target org with
  the caller's RLS scope removed (so cross-tenant objects are actually visible)
  and defaults to deny when a covered resource's org cannot be determined.
- **RLS coverage + robustness**: added a policy for `main_eventlog` (it carries
  its own `organization_id`); RLS policies now cast the tenant GUC via
  `NULLIF(current_setting(...), '')::int` so the empty "no scope" sentinel can't
  raise. New migrations `0209`, `0210` (idempotent).
- **`import_from_awx` trust boundary**: superuser / system-role promotion from
  the source is gated behind `--grant-superusers` (off by default, logged);
  custom credential-type injectors are dropped for admin re-approval unless
  `--trust-injectors` is given; secrets are read from `AWX_TOKEN` / `AWX_PASSWORD`
  in preference to argv.
- **SSO account-takeover fix**: `associate_by_email` removed from the auth
  pipeline — accounts associate by provider UID, not by matching email address.
- **Tenant provisioning** refuses to silently reuse an existing username (which
  discarded the supplied password and cross-linked accounts) unless
  `attach_existing_admin` is set.
- **IaC scanner path traversal**: a job template's `playbook` field can no
  longer point the scanner outside the project checkout (absolute / `..`).
- **Rate limiter** logs Redis outages loudly and honours a new
  `TENANCY_RATE_LIMIT_FAIL_CLOSED` setting (default open for availability).

### Fixed
- **Tenancy audit events could never be written.** Migration `0205` declares a
  `NOT NULL description` column on `TenantQuotaEvent` and `TenantIsolationEvent`,
  but both models extend `CreatedModifiedModel`, which does not provide that
  field — so every insert raised `IntegrityError` and the event was lost. The
  field is now declared on both models (matching the existing migration state; no
  new migration). Surfaced once the strict isolation gate started actually
  blocking cross-tenant reads and tried to record them.
- `pytest.ini` pointed `DJANGO_SETTINGS_MODULE` at the pre-rename
  `awx.main.tests.settings_for_test`, which no longer exists — the test suite
  could not start. Corrected to `forail.main.tests.settings_for_test`.
- `TenantQueueRouter.ROUTABLE_TASKS` still referenced the pre-rename
  `awx.main.tasks.*` task names; corrected to `forail.main.tasks.*`.

## [2026.06.0] - 2026-06-14

### Changed
- **Renamed `forge` → `forail`** across the entire project (organization `forgeplatform` → `forail-platform`): the `forail` Python package, image references (`ghcr.io/forail-platform/forail-*`), CLI, and all documentation/URLs. The GitHub organization and repositories were renamed to match.
- Versioning unified across all platform components to CalVer `2026.06.0`.


## [2026.05.0] - 2026-05-22

### Fixed
- `DriftAlertRule` rows could not be cascade-deleted from an
  Organization: the original `0198_drift_models` migration omitted
  the `created_by` / `modified_by` FK columns inherited from
  `PrimordialModel`, so any ORM query that joined the audit columns
  blew up with `psycopg.UndefinedColumn`. Symptom in the wild was
  `DELETE /api/v2/organizations/{id}/` returning HTTP 500 and the
  forail-operator finalizer hanging. Migration `0208` backfills both
  columns nullable + SET_NULL; a schema-level regression test in
  `tests_standalone/test_drift_audit_fields_schema.py` keeps the
  same gap from re-opening.

## [2026.04.0] - 2026-04-17

### Added
- Multi-Tenancy v2: per-tenant Celery queue routing and per-tenant
  API rate limiting (token bucket via Redis)
- Recommendations engine with 12 rules and REST API
- Standalone tests separated from the AWX-inherited test suite
- Podman installed in the runtime image for EE container isolation
- `23-recommendations` API reference doc
- Assistant API surface for the Ollama+RAG chat sidecar

### Changed
- Renamed all `awx-*` references to `forail-*` in user-facing strings,
  CLI commands (`forail-manage`), Django app labels, and docs
- Cleaned up legacy AWX docs and updated README links

### Fixed
- psycopg 3.2 API break in `PubSub.current_notifies`
- Migration ordering for fresh installs against existing AWX databases
