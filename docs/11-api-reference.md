# 11 — API Reference

Forge REST API reference. All endpoints are under `/api/v2/`.

---

## Authentication

### Session (browser)

```bash
curl -c cookies.txt -X POST \
  -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "password"}' \
  https://forge.example.com/api/login/

curl -b cookies.txt https://forge.example.com/api/v2/me/
```

### Token (API clients)

```bash
# Create a token
curl -u admin:password -X POST \
  -H 'Content-Type: application/json' \
  -d '{"scope": "write"}' \
  https://forge.example.com/api/v2/tokens/

# Use the token
curl -H 'Authorization: Bearer <token>' \
  https://forge.example.com/api/v2/job_templates/
```

### Basic Auth

```bash
curl -u admin:password https://forge.example.com/api/v2/job_templates/
```

---

## Pagination and Filtering

### Pagination

```bash
GET /api/v2/jobs/?page=2&page_size=50
# count, next, previous, results
```

### Search

```bash
GET /api/v2/job_templates/?search=deploy          # Full-text
GET /api/v2/job_templates/?name=Deploy%20App       # Exact match
GET /api/v2/hosts/?name__contains=web              # Contains
GET /api/v2/hosts/?name__startswith=prod-          # Starts with
```

### Ordering

```bash
GET /api/v2/jobs/?order_by=-created                # Newest first
GET /api/v2/job_templates/?order_by=name           # Alphabetical
```

### Date filter

```bash
GET /api/v2/jobs/?created__gte=2026-03-01&created__lte=2026-03-31
GET /api/v2/jobs/?finished__isnull=true            # Still running
```

### By relationship

```bash
GET /api/v2/jobs/?job_template=5                   # Jobs from template 5
GET /api/v2/hosts/?inventory=10                    # Hosts in inventory 10
GET /api/v2/job_templates/?organization=1          # Templates in org 1
```

---

## Endpoints

### Job Templates

```bash
GET    /api/v2/job_templates/                      # List
POST   /api/v2/job_templates/                      # Create
GET    /api/v2/job_templates/{id}/                  # Detail
PATCH  /api/v2/job_templates/{id}/                  # Update
DELETE /api/v2/job_templates/{id}/                  # Delete
POST   /api/v2/job_templates/{id}/launch/           # Launch (creates a Job)
GET    /api/v2/job_templates/{id}/launch/           # What's needed to launch
POST   /api/v2/job_templates/{id}/copy/             # Copy
GET    /api/v2/job_templates/{id}/jobs/             # Execution history
GET    /api/v2/job_templates/{id}/survey_spec/      # Survey definition
POST   /api/v2/job_templates/{id}/survey_spec/      # Set survey
DELETE /api/v2/job_templates/{id}/survey_spec/      # Delete survey
POST   /api/v2/job_templates/{id}/survey_spec/dynamic_choices/  # Resolve dynamic choices
GET    /api/v2/job_templates/{id}/credentials/      # Credentials on the template
GET    /api/v2/job_templates/{id}/schedules/        # Schedules
```

### Jobs

```bash
GET    /api/v2/jobs/                               # List all jobs
GET    /api/v2/jobs/{id}/                           # Job detail
GET    /api/v2/jobs/{id}/stdout/                    # Job output (format=txt|json)
GET    /api/v2/jobs/{id}/job_events/                # All job events
GET    /api/v2/jobs/{id}/job_host_summaries/        # Host results
POST   /api/v2/jobs/{id}/cancel/                    # Cancel a running job
POST   /api/v2/jobs/{id}/relaunch/                  # Relaunch
```

### Unified Jobs (all types)

```bash
GET    /api/v2/unified_jobs/                       # ALL: jobs, project updates, inventory syncs...
GET    /api/v2/unified_jobs/?type=job              # Only playbook jobs
GET    /api/v2/unified_jobs/?type=project_update   # Only project syncs
```

### Projects

```bash
GET    /api/v2/projects/                           # List
POST   /api/v2/projects/                           # Create
PATCH  /api/v2/projects/{id}/                       # Update
POST   /api/v2/projects/{id}/update/                # Trigger SCM sync
GET    /api/v2/projects/{id}/playbooks/             # List playbooks in the project
```

### Inventories, Hosts, Groups

```bash
GET    /api/v2/inventories/                        # List inventories
POST   /api/v2/inventories/                        # Create
GET    /api/v2/inventories/{id}/hosts/             # Hosts in inventory
POST   /api/v2/inventories/{id}/hosts/             # Add host
GET    /api/v2/inventories/{id}/groups/            # Groups in inventory
POST   /api/v2/inventories/{id}/groups/            # Add group
GET    /api/v2/inventories/{id}/inventory_sources/ # Cloud sync sources

GET    /api/v2/hosts/                              # All hosts (global)
PATCH  /api/v2/hosts/{id}/                          # Update host
GET    /api/v2/hosts/{id}/ansible_facts/           # Host facts

POST   /api/v2/groups/{id}/hosts/                  # Add host to group {id: host_id}
POST   /api/v2/groups/{id}/children/               # Add child group {id: group_id}
```

### Inventory Sources (Cloud Sync)

```bash
POST   /api/v2/inventories/{id}/inventory_sources/
# source: ec2, gce, azure_rm, vmware, openstack, satellite6, scm, custom
POST   /api/v2/inventory_sources/{id}/update/      # Trigger sync
```

### Credentials

```bash
GET    /api/v2/credential_types/                   # Available types
GET    /api/v2/credentials/                        # List credentials
POST   /api/v2/credentials/                        # Create credential
PATCH  /api/v2/credentials/{id}/                    # Update
```

### Workflows

```bash
POST   /api/v2/workflow_job_templates/             # Create workflow
POST   /api/v2/workflow_job_templates/{id}/workflow_nodes/  # Add node
POST   /api/v2/workflow_job_template_nodes/{id}/success_nodes/  # Connect success
POST   /api/v2/workflow_job_template_nodes/{id}/failure_nodes/  # Connect failure
POST   /api/v2/workflow_job_template_nodes/{id}/always_nodes/   # Connect always
POST   /api/v2/workflow_job_templates/{id}/launch/  # Launch workflow
GET    /api/v2/workflow_jobs/{id}/workflow_nodes/   # Status of each step
```

### Users, Teams, Organizations

```bash
GET    /api/v2/users/                              # List users
POST   /api/v2/users/                              # Create user
GET    /api/v2/teams/                              # List teams
POST   /api/v2/teams/{id}/users/                   # Add user to team {id: user_id}
POST   /api/v2/roles/{id}/users/                   # Assign role to user {id: user_id}
POST   /api/v2/roles/{id}/teams/                   # Assign role to team {id: team_id}
```

### Schedules

```bash
GET    /api/v2/schedules/                          # List schedules
POST   /api/v2/schedules/                          # Create schedule
# rrule format: "DTSTART:20260315T020000Z RRULE:FREQ=DAILY;INTERVAL=1"
POST   /api/v2/schedules/preview/                  # Preview upcoming runs
```

### Notifications

```bash
GET    /api/v2/notification_templates/             # List
POST   /api/v2/notification_templates/             # Create
# notification_type: email, slack, webhook, pagerduty, grafana, mattermost, twilio...
POST   /api/v2/notification_templates/{id}/test/   # Send test notification
```

### System

```bash
GET    /api/v2/ping/                               # Health check (no auth)
GET    /api/v2/config/                             # Version, license, info
GET    /api/v2/me/                                 # Current user
GET    /api/v2/activity_stream/                    # Activity stream (change log)
GET    /api/v2/audit_events/                       # Audit events (immutable security log)
GET    /api/v2/audit_events/?format=csv            # Export audit events as CSV
GET    /api/v2/audit_events/?format=siem           # Export audit events for SIEM (flat JSON)
GET    /api/v2/audit_events/{id}/                  # Audit event detail

# Event-Driven Automation (EDA)
GET    /api/v2/event_rules/                           # List event rules
POST   /api/v2/event_rules/                           # Create event rule
GET    /api/v2/event_rules/{id}/                      # Event rule detail
PATCH  /api/v2/event_rules/{id}/                      # Update event rule
DELETE /api/v2/event_rules/{id}/                      # Delete event rule
GET    /api/v2/event_rules/{id}/webhook_key/          # Get webhook HMAC key
POST   /api/v2/event_rules/{id}/webhook_key/          # Rotate webhook key
GET    /api/v2/event_rules/{id}/event_logs/           # Logs for this rule
POST   /api/v2/event_rules/{id}/test/                 # Dry-run condition test
POST   /api/v2/event_rules/{id}/enable/               # Enable rule
POST   /api/v2/event_rules/{id}/disable/              # Disable rule

GET    /api/v2/event_logs/                            # List all event logs
GET    /api/v2/event_logs/{id}/                       # Event log detail (payload, conditions, actions)

GET    /api/v2/outbound_webhooks/                     # List outbound webhooks
POST   /api/v2/outbound_webhooks/                     # Create outbound webhook
GET    /api/v2/outbound_webhooks/{id}/                # Detail
PATCH  /api/v2/outbound_webhooks/{id}/                # Update
DELETE /api/v2/outbound_webhooks/{id}/                # Delete
POST   /api/v2/outbound_webhooks/{id}/test/           # Send test payload

POST   /api/v2/eda_webhooks/{webhook_path}/           # Public receiver (no auth, HMAC verified)
```

### Event Rule — Create Example

```bash
curl -X POST https://forge.example.com/api/v2/event_rules/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Deploy on GitHub push",
    "organization": 1,
    "source_type": "webhook_github",
    "webhook_path": "github-deploy",
    "conditions": [
      {"jinja2_expression": "event.ref == \"refs/heads/main\"", "description": "Main branch only"}
    ],
    "actions": [
      {"action_type": "launch_job_template", "target_id": 5}
    ]
  }'
```

### Drift Detection

```bash
GET    /api/v2/fact_snapshots/                          # List snapshots (filter: host, inventory, job)
GET    /api/v2/fact_snapshots/{id}/                     # Snapshot detail (includes full facts)

GET    /api/v2/drift_detections/                        # List drift items (filter: host, category, severity, acknowledged)
GET    /api/v2/drift_detections/{id}/                   # Drift detail (before/after diff)
POST   /api/v2/drift_detections/{id}/acknowledge/       # Mark acknowledged
POST   /api/v2/drift_detections/compare/                # Compare two snapshots
GET    /api/v2/drift_detections/export/                 # CSV compliance report
GET    /api/v2/drift_detections/summary/                # Dashboard stats

GET    /api/v2/drift_alert_rules/                       # List alert rules
POST   /api/v2/drift_alert_rules/                       # Create alert rule
GET    /api/v2/drift_alert_rules/{id}/                  # Detail
PATCH  /api/v2/drift_alert_rules/{id}/                  # Update
DELETE /api/v2/drift_alert_rules/{id}/                  # Delete
POST   /api/v2/drift_alert_rules/{id}/enable/           # Enable
POST   /api/v2/drift_alert_rules/{id}/disable/          # Disable

GET    /api/v2/drift_alerts/                            # List triggered alerts
GET    /api/v2/drift_alerts/{id}/                       # Alert detail

GET    /api/v2/hosts/{id}/drift/                        # Host drift history
```

### Self-Service Portal

```bash
GET    /api/v2/service_catalog_items/                   # List catalog items (filter: category, enabled, search, organization)
POST   /api/v2/service_catalog_items/                   # Create catalog item (admin)
GET    /api/v2/service_catalog_items/{id}/              # Detail
PATCH  /api/v2/service_catalog_items/{id}/              # Update
DELETE /api/v2/service_catalog_items/{id}/              # Delete
GET    /api/v2/service_catalog_items/{id}/launch_data/  # Survey spec from underlying JT/WFJT (+ per-node surveys)
GET    /api/v2/service_catalog_items/{id}/requests/     # All requests for a catalog item
POST   /api/v2/service_catalog_items/{id}/submit/       # End-user submit (extra_vars, node_survey_data, justification)

GET    /api/v2/service_requests/                        # List service requests (filter: mine, status, catalog_item)
GET    /api/v2/service_requests/pending_approvals/      # Approval inbox (filtered to caller's authority)
GET    /api/v2/service_requests/{id}/                   # Detail
DELETE /api/v2/service_requests/{id}/                   # Delete (only pending/rejected)
POST   /api/v2/service_requests/{id}/approve/           # Approve & launch
POST   /api/v2/service_requests/{id}/reject/            # Reject ({reason})
```

See `docs/17-self-service-portal.md` for the lifecycle, approver
permission rules, and a deeper architectural overview.

### WebAuthn / FIDO2

```bash
GET    /api/v2/webauthn/credentials/                    # List your registered credentials
PATCH  /api/v2/webauthn/credentials/{id}/               # Rename ({label})
DELETE /api/v2/webauthn/credentials/{id}/               # Delete a credential

POST   /api/v2/webauthn/register/begin/                 # publicKeyCredentialCreationOptions
POST   /api/v2/webauthn/register/complete/              # Verify attestation, store credential

POST   /api/v2/webauthn/authenticate/begin/             # publicKeyCredentialRequestOptions ({username?})
POST   /api/v2/webauthn/authenticate/complete/          # Verify assertion → MFA satisfied OR passwordless login
```

The OIDC client redirects through `/sso/login/oidc/` (handled by
`social-auth-app-django`). Configuration lives in Settings → Generic
OIDC. See `docs/18-oidc-webauthn.md` for the full architecture.

### Policy-as-Code (OPA)

```bash
GET    /api/v2/policies/                              # List (filter: enabled, applies_to, organization, search)
POST   /api/v2/policies/                              # Create (admin)
GET    /api/v2/policies/{id}/                         # Detail
PATCH  /api/v2/policies/{id}/                         # Update
DELETE /api/v2/policies/{id}/                         # Delete
POST   /api/v2/policies/{id}/enable/                  # Enable
POST   /api/v2/policies/{id}/disable/                 # Disable
POST   /api/v2/policies/{id}/test/                    # Dry-run ({input: {...}})

GET    /api/v2/policy_decisions/                      # Audit log (filter: decision, policy, unified_job, since)
GET    /api/v2/policy_decisions/{id}/                 # Decision detail (full context JSON)
```

See `docs/19-policy-as-code.md` for the architecture, the OPA wire
format, and the launch hook diagram.

### IaC Scanning & Supply Chain Security

```bash
GET    /api/v2/scanners/                              # List (filter: enabled, tool, applies_to, organization, search)
POST   /api/v2/scanners/                              # Create (admin)
GET    /api/v2/scanners/{id}/                         # Detail
PATCH  /api/v2/scanners/{id}/                         # Update
DELETE /api/v2/scanners/{id}/                         # Delete
POST   /api/v2/scanners/{id}/enable/                  # Enable
POST   /api/v2/scanners/{id}/disable/                 # Disable

GET    /api/v2/scan_results/                          # Audit log (filter: scanner, status, unified_job, since)
GET    /api/v2/scan_results/{id}/                     # Result detail with embedded findings
```

See `docs/20-iac-scanning.md` for the architecture, tool adapters
(ansible-lint / checkov / pip-audit), severity threshold model, and
the launch hook diagram.

### Observability (OpenTelemetry)

```bash
GET    /api/v2/observability/                          # Current OTel config + best-effort collector health probe (admin only)
```

Response shape:

```json
{
  "enabled": true,
  "service_name": "forge",
  "exporter_endpoint": "http://forge-otel-collector:4317",
  "sampler": "parentbased_traceidratio",
  "sampler_arg": "0.1",
  "collector_healthy": true,
  "collector_last_check": "2026-04-09T15:42:00Z"
}
```

See `docs/21-observability.md` for the architecture, env vars,
instrumented seams, and metric catalog.

### Drift Alert Rule — Create Example

```bash
curl -X POST https://forge.example.com/api/v2/drift_alert_rules/ \
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

### Forge Analytics

```bash
GET    /api/v2/forge_analytics/                    # Root (links to all sub-endpoints)
GET    /api/v2/forge_analytics/job_trends/         # Job duration trends (params: period, granularity)
GET    /api/v2/forge_analytics/success_rate/       # Success/failure rates over time
GET    /api/v2/forge_analytics/top_templates/      # Most-used templates (params: period, limit)
GET    /api/v2/forge_analytics/busiest_hosts/      # Hosts with most activity
GET    /api/v2/forge_analytics/host_coverage/      # Automation coverage per inventory
GET    /api/v2/forge_analytics/failure_analysis/   # Failure breakdown by template and host
GET    /api/v2/forge_analytics/time_savings/       # Time savings calculator (params: manual_multiplier)
```

### Administration

```bash
GET    /api/v2/instances/                          # Cluster nodes
GET    /api/v2/instance_groups/                    # Instance groups
GET    /api/v2/settings/                           # List setting categories
GET    /api/v2/settings/jobs/                      # Job settings
PATCH  /api/v2/settings/jobs/                      # Change job settings
```

### Ad-Hoc Commands

```bash
# Run a one-off command
POST /api/v2/ad_hoc_commands/
# module_name: ping, shell, command, copy, yum, apt...
# module_args: arguments for the module (e.g., "uptime" for shell)
```

---

## Watch Out

1. **The `related` field in every response** contains URLs to all related resources.
   Use this for navigation — don't construct URLs manually.

2. **`summary_fields`** provides inline data about relationships (organization name, project name...).
   This eliminates the need for additional API calls.

3. **POST for M2M relationships** uses the format `{"id": <target_id>}` for attach,
   and `{"id": <target_id>, "disassociate": true}` for detach.

4. **The launch endpoint** (GET) returns information about what's needed to launch —
   which parameters can be overridden and which are required.

5. **All list endpoints are paginated.** Default is 25, max 200.
   Use the `page_size` parameter to control this.
