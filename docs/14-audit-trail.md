# 14 — Improved Audit Trail

Forail provides two complementary audit mechanisms:

1. **Activity Stream** — existing change log (create/update/delete/associate), now enhanced with IP, User-Agent, and session tracking
2. **Audit Events** — new immutable, append-only security audit log for compliance-grade auditing

---

## Activity Stream Enhancements

The existing `ActivityStream` model now captures request metadata on every entry:

| Field              | Type                  | Description                                        |
| ------------------ | --------------------- | -------------------------------------------------- |
| `actor_ip`         | GenericIPAddressField | IP address of the actor (supports X-Forwarded-For) |
| `actor_user_agent` | CharField(512)        | User-Agent header from the request                 |
| `actor_session_id` | CharField(64)         | Django session ID at the time of the event         |

These fields are automatically populated by `RequestContextMiddleware` which
extracts the data from each incoming HTTP request and stores it in thread-local
storage. The `ActivityStream.save()` method reads from this context on first save.

### API Response

Activity stream entries now include the new fields in the API response:

```json
{
  "id": 123,
  "timestamp": "2026-04-02T12:00:00Z",
  "operation": "update",
  "actor_ip": "203.0.113.50",
  "actor_user_agent": "Mozilla/5.0 ...",
  "actor_session_id": "abc123def456",
  "changes": { ... },
  "summary_fields": { "actor": { "id": 1, "username": "admin" } }
}
```

---

## Audit Events (AuditEvent Model)

### Overview

`AuditEvent` is a new, immutable audit log model designed for compliance and
security auditing. Unlike Activity Stream (which tracks all CRUD operations),
Audit Events focus on security-sensitive operations:

- **Authentication** — login, logout, login failures, token creation
- **Credential Access** — who used which credential, when, for which job
- **Permission Changes** — role grants, role revocations, team membership changes
- **System Events** — configuration changes, maintenance operations

### Immutability

Audit events are append-only:

- `save()` raises `ValueError` if the entry already has a primary key (no updates)
- `delete()` raises `ValueError` (no deletions)
- Records can only be created, never modified or removed

### Model Fields

| Field              | Type                  | Description                                                                   |
| ------------------ | --------------------- | ----------------------------------------------------------------------------- |
| `timestamp`        | DateTimeField         | Auto-populated creation time (indexed)                                        |
| `actor`            | ForeignKey(User)      | User who triggered the event (nullable)                                       |
| `actor_username`   | CharField             | Denormalized username (survives user deletion)                                |
| `actor_ip`         | GenericIPAddressField | Source IP address                                                             |
| `actor_user_agent` | CharField(512)        | User-Agent string                                                             |
| `actor_session_id` | CharField(64)         | Session ID                                                                    |
| `category`         | CharField             | `auth`, `credential_access`, `permission_change`, `resource_change`, `system` |
| `severity`         | CharField             | `info`, `warning`, `critical`                                                 |
| `action`           | CharField             | Specific action, e.g. `login`, `credential_used`, `role_granted`              |
| `description`      | TextField             | Human-readable event description                                              |
| `resource_type`    | CharField             | Affected resource type (e.g. `credential`, `team`)                            |
| `resource_id`      | IntegerField          | ID of affected resource                                                       |
| `resource_name`    | CharField             | Name of affected resource (denormalized)                                      |
| `action_node`      | CharField             | Cluster node where event occurred                                             |
| `detail`           | JSONField             | Additional structured data                                                    |
| `organization`     | ForeignKey            | Organization scope (for RBAC filtering)                                       |

---

## API Endpoints

### List Audit Events

```
GET /api/v2/audit_events/
```

**Query Parameters:**

| Parameter         | Description                                                                                       |
| ----------------- | ------------------------------------------------------------------------------------------------- |
| `category`        | Filter by category: `auth`, `credential_access`, `permission_change`, `resource_change`, `system` |
| `severity`        | Filter by severity: `info`, `warning`, `critical`                                                 |
| `action`          | Filter by specific action string                                                                  |
| `actor__username` | Filter by actor username                                                                          |
| `resource_type`   | Filter by resource type                                                                           |
| `resource_id`     | Filter by resource ID                                                                             |
| `timestamp__gte`  | Events after this ISO datetime                                                                    |
| `timestamp__lte`  | Events before this ISO datetime                                                                   |
| `organization`    | Filter by organization ID                                                                         |
| `format`          | Response format: `json` (default), `csv`, `siem`                                                  |

### Export Formats

**CSV Export:**

```
GET /api/v2/audit_events/?format=csv
```

Returns a streaming CSV download (max 10,000 rows) with columns:
id, timestamp, actor_username, actor_ip, category, severity, action,
description, resource_type, resource_id, resource_name, action_node.

**SIEM JSON Export:**

```
GET /api/v2/audit_events/?format=siem
```

Returns flat JSON optimized for SIEM ingestion (Splunk, ELK, Datadog):

- `detail` dict fields are flattened with `detail_` prefix
- `source: "forail"` and `event_type: "<category>.<action>"` are added
- No nested objects — every field is at the top level

### Detail

```
GET /api/v2/audit_events/{id}/
```

### Permissions

- **Superusers and System Auditors**: see all audit events
- **Regular users**: only see events in their organizations

---

## Credential Access Logging

When a job is created and uses credentials, each credential access is
automatically logged as an audit event:

```json
{
  "category": "credential_access",
  "action": "credential_used",
  "severity": "info",
  "actor_username": "admin",
  "actor_ip": "10.0.1.5",
  "resource_type": "credential",
  "resource_id": 42,
  "resource_name": "Production SSH Key",
  "description": "Credential \"Production SSH Key\" (id=42) used for Job #100",
  "detail": {
    "job_id": 100,
    "job_type": "Job",
    "credential_type": "Machine",
    "credential_type_kind": "ssh"
  }
}
```

This logging happens in `forail/main/signals.py` in the `activity_stream_create`
handler when a `Job` instance is created.

---

## Utility Functions

Located in `forail/main/utils/audit.py`:

```python
from forail.main.utils.audit import log_credential_access, log_auth_event, log_permission_change

# Log credential usage
log_credential_access(credential, job=job, actor=user)

# Log authentication event
log_auth_event('login', actor=user, description='User logged in from 10.0.1.5')
log_auth_event('login_failed', severity='warning', description='Invalid password for admin')

# Log permission change
log_permission_change('role_granted', actor=admin, resource_type='team',
                      resource_id=5, resource_name='DevOps',
                      detail={'role': 'admin', 'target_user': 'john'})
```

All utility functions catch exceptions internally and log them — they never
cause the calling operation to fail.

---

## Middleware

`RequestContextMiddleware` in `forail/main/middleware.py`:

- Extracts IP (from `X-Forwarded-For` or `REMOTE_ADDR`), User-Agent, and session ID
- Stores in thread-local storage for signal handlers to read
- Cleans up after each response
- Must be placed after `AuthenticationMiddleware` in `MIDDLEWARE` setting

---

## Frontend

The Audit Log page is available at `/audit` in the Forail UI:

- **Filters**: category, severity, username, resource type
- **Expandable rows**: click to see IP, user agent, session ID, node, detail JSON
- **CSV export**: download button for filtered results
- **Pagination**: configurable page size (10/25/50)
- **Navigation**: accessible from sidebar under "Views" section

The Activity Stream page (`/activity`) also displays the new IP and
user agent fields where available.
