# Changelog

All notable changes to the Forail Backend will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to CalVer (`YYYY.MM.PATCH`).

## [Unreleased]

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

### Fixed
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
