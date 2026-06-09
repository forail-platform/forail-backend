# 16 — Drift Detection

Automatic configuration change tracking between Ansible runs. Captures host
fact snapshots, compares them to detect drift, and alerts when thresholds
are exceeded.

---

## Architecture

```
Job completes (fact cache enabled)
         │
         ▼
  finish_fact_cache()          ── updates host.ansible_facts
         │
         ▼
  capture_fact_snapshot        ── Celery task (async)
         │                        computes SHA-256 hash of facts
         │                        skips if hash matches previous snapshot
         ▼
  HostFactSnapshot created     ── full ansible_facts stored
         │
         ▼
  detect_drift                 ── Celery task (async)
         │                        compares with previous snapshot
         │                        categorizes changes (packages, kernel, ...)
         │                        assigns severity (low → critical)
         ▼
  DriftDetection records       ── one per changed fact key
         │
         ▼
  evaluate_drift_alerts        ── Celery task (async)
         │                        checks all enabled DriftAlertRules
         │                        threshold, window, cooldown
         ▼
  DriftAlert + notification    ── if threshold exceeded
```

The entire pipeline is asynchronous — `capture_fact_snapshot.delay(job.id)`
is called from `RunJob.post_run_hook()` after `finish_fact_cache()` completes,
so it does not slow down job completion.

---

## Models

### HostFactSnapshot

Point-in-time capture of `ansible_facts` for a single host.

| Field          | Type                | Description                                       |
| -------------- | ------------------- | ------------------------------------------------- |
| `host`         | FK → Host           | The host whose facts were captured                |
| `job`          | FK → Job (nullable) | The job that triggered the capture                |
| `inventory`    | FK → Inventory      | Inherited from host                               |
| `organization` | FK → Organization   | Inherited from inventory                          |
| `captured_at`  | DateTime            | When the snapshot was taken                       |
| `facts`        | JSON                | Full `ansible_facts` dictionary                   |
| `facts_hash`   | CharField(64)       | SHA-256 of sorted JSON — for quick equality check |

**Key behavior:** A snapshot is only created when `facts_hash` differs from
the most recent snapshot for the same host. This prevents storing duplicate
snapshots when facts haven't changed.

### DriftDetection

A single detected configuration change between two consecutive snapshots.

| Field             | Type                  | Description                                                      |
| ----------------- | --------------------- | ---------------------------------------------------------------- |
| `host`            | FK → Host             | Which host changed                                               |
| `snapshot_before` | FK → HostFactSnapshot | Previous state                                                   |
| `snapshot_after`  | FK → HostFactSnapshot | New state                                                        |
| `job`             | FK → Job              | Which job caused the change                                      |
| `category`        | CharField             | packages, services, users_groups, network, mounts, kernel, other |
| `severity`        | CharField             | low, medium, high, critical                                      |
| `fact_path`       | CharField             | Top-level fact key (e.g. `ansible_packages`)                     |
| `summary`         | CharField             | Human-readable change description                                |
| `detail`          | JSON                  | `{before, after, diff_type}`                                     |
| `acknowledged`    | Boolean               | Whether an admin has reviewed this change                        |
| `acknowledged_by` | FK → User             | Who acknowledged                                                 |
| `acknowledged_at` | DateTime              | When acknowledged                                                |

### Category Classification

| Category       | Matched facts                                                    | Default severity |
| -------------- | ---------------------------------------------------------------- | ---------------- |
| `packages`     | ansible*packages, ansible_pkg_mgr, \_package*, *pip*             | medium           |
| `services`     | ansible*services, ansible_service_mgr, \_systemd*                | medium           |
| `users_groups` | ansible*user\*\*, *user*, *group*,*passwd\*                      | high             |
| `network`      | ansible*all_ipv4/6_addresses, ansible_interfaces, \_tcp*, *port* | high             |
| `mounts`       | ansible*mounts, ansible_devices, \_disk*, *lvm*                  | medium           |
| `kernel`       | ansible_kernel\*, ansible_sysctl, ansible_selinux                | critical         |
| `other`        | Everything else                                                  | low              |

**Volatile keys skipped:** `ansible_date_time`, `ansible_uptime_seconds`,
`ansible_local`, `module_setup`, `gather_subset`.

### DriftAlertRule

User-defined rule for alerting when drift exceeds a threshold.

| Field                      | Type                      | Description                                          |
| -------------------------- | ------------------------- | ---------------------------------------------------- |
| `name`                     | CharField                 | Rule name (unique per org)                           |
| `organization`             | FK → Organization         | Scope                                                |
| `enabled`                  | Boolean                   | Active or paused                                     |
| `inventory`                | FK → Inventory (optional) | Filter by inventory                                  |
| `host_filter`              | CharField                 | fnmatch pattern (e.g. `web-*`)                       |
| `categories`               | JSON list                 | Which drift categories to match (empty = all)        |
| `severity_min`             | CharField                 | Minimum severity to count (low/medium/high/critical) |
| `threshold_count`          | Integer                   | How many drift items trigger the alert               |
| `threshold_window_minutes` | Integer                   | Time window for counting                             |
| `cooldown_minutes`         | Integer                   | Minimum time between alert firings                   |
| `notification_template`    | FK → NotificationTemplate | Where to send alert                                  |

### DriftAlert

Immutable record of a triggered alert.

| Field                 | Type                | Description                       |
| --------------------- | ------------------- | --------------------------------- |
| `alert_rule`          | FK → DriftAlertRule | Which rule triggered              |
| `host`                | FK → Host           | Which host caused it              |
| `drift_count`         | Integer             | How many drift items were counted |
| `summary`             | Text                | Human-readable description        |
| `notification_status` | CharField           | pending, sent, failed             |
| `notification_error`  | Text                | Error message if send failed      |

---

## API Endpoints

### Fact Snapshots (read-only)

```bash
GET    /api/v2/fact_snapshots/                          # List (filterable by host, inventory, job)
GET    /api/v2/fact_snapshots/{id}/                     # Detail (includes full facts)
```

### Drift Detections (read-only + acknowledge)

```bash
GET    /api/v2/drift_detections/                        # List (filter: host, inventory, category, severity, acknowledged)
GET    /api/v2/drift_detections/{id}/                   # Detail (includes before/after diff)
POST   /api/v2/drift_detections/{id}/acknowledge/       # Mark as acknowledged
POST   /api/v2/drift_detections/compare/                # Compare two snapshots: {snapshot_a, snapshot_b}
GET    /api/v2/drift_detections/export/                 # CSV compliance report (filter: host, inventory, date range)
GET    /api/v2/drift_detections/summary/                # Dashboard stats: {total, unacknowledged, by_category, by_severity}
```

### Drift Alert Rules (CRUD)

```bash
GET    /api/v2/drift_alert_rules/                       # List
POST   /api/v2/drift_alert_rules/                       # Create
GET    /api/v2/drift_alert_rules/{id}/                  # Detail
PATCH  /api/v2/drift_alert_rules/{id}/                  # Update
DELETE /api/v2/drift_alert_rules/{id}/                  # Delete
POST   /api/v2/drift_alert_rules/{id}/enable/           # Enable
POST   /api/v2/drift_alert_rules/{id}/disable/          # Disable
```

### Drift Alerts (read-only)

```bash
GET    /api/v2/drift_alerts/                            # List (filter: alert_rule, host, notification_status)
GET    /api/v2/drift_alerts/{id}/                       # Detail
```

### Host Drift History (nested)

```bash
GET    /api/v2/hosts/{id}/drift/                        # All drift for a specific host
```

---

## Alert Rule — Create Example

```bash
curl -X POST https://forail.example.com/api/v2/drift_alert_rules/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Critical kernel changes",
    "organization": 1,
    "categories": ["kernel", "users_groups"],
    "severity_min": "high",
    "threshold_count": 1,
    "threshold_window_minutes": 60,
    "cooldown_minutes": 30,
    "notification_template": 5
  }'
```

---

## CSV Compliance Export

```bash
# Export all drift for an inventory in the last 30 days
curl -H "Authorization: Bearer <token>" \
  "https://forail.example.com/api/v2/drift_detections/export/?inventory=3&date_from=2026-03-01" \
  -o drift_report.csv
```

Output columns: ID, Host, Detected At, Category, Severity, Fact Path,
Summary, Diff Type, Acknowledged.

---

## Snapshot Cleanup

Periodic task `cleanup_old_snapshots` runs as a Celery beat task:

- Default retention: 90 days
- Always keeps at least 2 snapshots per host
- Run manually: `forail-manage shell -c "from forail.main.tasks.drift import cleanup_old_snapshots; cleanup_old_snapshots()"`

---

## Frontend

Four pages under the **Compliance** sidebar section:

| Page                    | Route                    | Description                                               |
| ----------------------- | ------------------------ | --------------------------------------------------------- |
| Drift Detections        | `/drift_detections`      | Filterable list with category/severity badges, CSV export |
| Drift Detection Detail  | `/drift_detections/:id`  | Before/after JSON diff, acknowledge button                |
| Drift Alert Rules       | `/drift_alert_rules`     | CRUD list with create/edit/enable/disable                 |
| Drift Alert Rule Detail | `/drift_alert_rules/:id` | Config summary, recent triggered alerts                   |
| Drift Alerts            | `/drift_alerts`          | Read-only list of triggered alerts                        |
| Drift Alert Detail      | `/drift_alerts/:id`      | Alert summary, notification status/error                  |
| Fact Snapshots          | `/fact_snapshots`        | Browse captured snapshots by host/job                     |

---

## Security

- **RBAC:** All endpoints require authentication. Non-admin users only see
  drift for hosts in their organization.
- **No write access to drift data:** DriftDetection records are created
  automatically by the system — users can only acknowledge, not modify.
- **Immutable snapshots:** HostFactSnapshot records cannot be updated or
  deleted through the API.
