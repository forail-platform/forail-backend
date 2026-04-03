# Event-Driven Automation (EDA)

Forge EDA enables webhook-based event routing with user-defined rules.
When an external system sends a webhook (GitHub push, Alertmanager alert,
PagerDuty incident, etc.), Forge evaluates conditions and automatically
launches job templates, workflows, or sends notifications.

---

## Architecture

```
External System ──POST──> /api/v2/eda_webhooks/<path>/
                              │
                              ├── HMAC signature verification
                              ├── EventLog created (status: received)
                              └── Celery task dispatched
                                      │
                                      ├── Evaluate Jinja2 conditions
                                      ├── If matched: execute actions
                                      │   ├── Launch JobTemplate
                                      │   ├── Launch WorkflowJobTemplate
                                      │   └── Send NotificationTemplate
                                      └── Log results + AuditEvent
```

Outbound webhooks work in reverse — when a job completes, Forge POSTs
a signed JSON payload to configured external URLs.

---

## Models

### EventRule

The core model. Maps a webhook endpoint to conditions and actions.

| Field | Type | Description |
|-------|------|-------------|
| name | CharField | Rule name (unique per organization) |
| organization | FK(Organization) | RBAC scoping |
| enabled | BooleanField | Active/inactive toggle |
| source_type | CharField | `webhook_generic`, `webhook_github`, `webhook_gitlab`, `alertmanager`, `pagerduty`, `datadog`, `cloudwatch` |
| webhook_path | SlugField(unique) | URL path segment: `/api/v2/eda_webhooks/<path>/` |
| webhook_key | CharField | HMAC shared secret (auto-generated) |
| conditions | JSONField | List of `{jinja2_expression, description}` |
| actions | JSONField | List of `{action_type, target_id, extra_vars, description}` |
| throttle_seconds | IntegerField | Min interval between firings (0 = no limit) |
| last_fired_at | DateTimeField | Last firing timestamp |
| fire_count | IntegerField | Total firing count |

### EventLog

Immutable log of every received webhook and its evaluation outcome.

| Field | Type | Description |
|-------|------|-------------|
| event_rule | FK(EventRule) | Associated rule (nullable) |
| event_rule_name | CharField | Denormalized (preserved after deletion) |
| source_type | CharField | Source type at time of event |
| source_ip | GenericIPAddress | Sender IP |
| event_type | CharField | e.g. `push`, `pull_request`, `alert` |
| event_guid | CharField | Unique ID for deduplication |
| payload | JSONField | Raw webhook body |
| headers | JSONField | Relevant HTTP headers |
| conditions_matched | BooleanField | Whether all conditions passed |
| condition_results | JSONField | Per-condition eval results |
| actions_triggered | JSONField | Per-action exec results |
| status | CharField | `received`, `matched`, `unmatched`, `throttled`, `action_fired`, `action_failed`, `error`, `signature_failed` |
| job_id | IntegerField | Launched job ID (if applicable) |

### OutboundWebhook

Push job status changes to external systems.

| Field | Type | Description |
|-------|------|-------------|
| name | CharField | Webhook name |
| organization | FK(Organization) | RBAC scoping |
| url | URLField | Target URL |
| webhook_key | CharField | HMAC signing secret |
| events | JSONField | List: `job.started`, `job.succeeded`, `job.failed`, `job.canceled`, `workflow.started`, `workflow.succeeded`, `workflow.failed` |
| custom_headers | JSONField | Extra headers to include |
| enabled | BooleanField | Active toggle |
| ssl_verify | BooleanField | Verify target SSL |

---

## API Endpoints

### Event Rules

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v2/event_rules/` | List rules |
| POST | `/api/v2/event_rules/` | Create rule |
| GET | `/api/v2/event_rules/{id}/` | Rule detail |
| PATCH | `/api/v2/event_rules/{id}/` | Update rule |
| DELETE | `/api/v2/event_rules/{id}/` | Delete rule |
| GET | `/api/v2/event_rules/{id}/webhook_key/` | Get webhook key |
| POST | `/api/v2/event_rules/{id}/webhook_key/` | Rotate key |
| GET | `/api/v2/event_rules/{id}/event_logs/` | Logs for this rule |
| POST | `/api/v2/event_rules/{id}/test/` | Dry-run test |
| POST | `/api/v2/event_rules/{id}/enable/` | Enable rule |
| POST | `/api/v2/event_rules/{id}/disable/` | Disable rule |

### Event Logs

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v2/event_logs/` | List logs |
| GET | `/api/v2/event_logs/{id}/` | Log detail |

### Outbound Webhooks

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v2/outbound_webhooks/` | List webhooks |
| POST | `/api/v2/outbound_webhooks/` | Create webhook |
| GET | `/api/v2/outbound_webhooks/{id}/` | Detail |
| PATCH | `/api/v2/outbound_webhooks/{id}/` | Update |
| DELETE | `/api/v2/outbound_webhooks/{id}/` | Delete |
| POST | `/api/v2/outbound_webhooks/{id}/test/` | Send test payload |

### Public Receiver

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/v2/eda_webhooks/{webhook_path}/` | Receive webhook (no auth, HMAC verified) |

---

## Conditions (Jinja2)

Conditions are Jinja2 expressions evaluated against the webhook payload.
All conditions must match (AND logic). Empty conditions = always match.

**Context variables:**

| Variable | Content |
|----------|---------|
| `event` | The webhook JSON payload |
| `headers` | Relevant HTTP headers |

**Examples:**

```yaml
# GitHub: only PR opened events
- jinja2_expression: "event.action == 'opened'"
  description: "Pull request opened"

# Alertmanager: only firing alerts for production
- jinja2_expression: "event.status == 'firing'"
  description: "Alert is firing"
- jinja2_expression: "'production' in event.commonLabels.environment"
  description: "Production environment"

# Generic: check for specific field value
- jinja2_expression: "event.severity == 'critical'"
  description: "Critical severity only"
```

---

## Actions

| action_type | target_id | Description |
|-------------|-----------|-------------|
| `launch_job_template` | JobTemplate ID | Launch with event payload as extra_vars |
| `launch_workflow` | WorkflowJobTemplate ID | Launch workflow |
| `send_notification` | NotificationTemplate ID | Send notification with event summary |

**Injected extra variables** (available in playbooks):

| Variable | Content |
|----------|---------|
| `forge_eda_event_type` | Event type (e.g. `push`) |
| `forge_eda_event_guid` | Unique event ID |
| `forge_eda_rule_name` | Rule name that fired |
| `forge_eda_payload` | Full webhook payload |

---

## Signature Verification

| Source Type | Method | Header |
|-------------|--------|--------|
| `webhook_github` | HMAC-SHA256 or HMAC-SHA1 | `X-Hub-Signature-256` or `X-Hub-Signature` |
| `webhook_gitlab` | Token comparison | `X-Gitlab-Token` |
| `webhook_generic` | HMAC-SHA256 | `X-Forge-Signature` |
| `alertmanager` | HMAC-SHA256 | `X-Forge-Signature` |
| Others | HMAC-SHA256 | `X-Forge-Signature` |

**X-Forge-Signature format:** `sha256=<hex_digest>`

To sign a payload with the webhook key:
```bash
echo -n '{"event":"test"}' | openssl dgst -sha256 -hmac 'YOUR_WEBHOOK_KEY'
```

---

## Security

- **HMAC verification** on all incoming webhooks
- **Jinja2 sandboxing** via `ImmutableSandboxedEnvironment` (no file access, no dangerous calls)
- **Rate limiting** via `throttle_seconds` per rule
- **Payload size limit**: 1MB max
- **Deduplication**: Duplicate `event_guid` values are rejected
- **RBAC**: Rules scoped to organizations, org admins manage rules
- **Audit trail**: Every rule firing creates an AuditEvent

---

## Quick Start

### 1. Create an Event Rule

```bash
curl -X POST https://forge.example.com/api/v2/event_rules/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Deploy on GitHub push to main",
    "organization": 1,
    "source_type": "webhook_github",
    "webhook_path": "github-deploy",
    "conditions": [
      {"jinja2_expression": "event.ref == \"refs/heads/main\"", "description": "Push to main"}
    ],
    "actions": [
      {"action_type": "launch_job_template", "target_id": 5, "description": "Run deploy playbook"}
    ]
  }'
```

### 2. Copy the webhook URL and key

From the response, note the `webhook_url` and retrieve the key:
```bash
curl https://forge.example.com/api/v2/event_rules/1/webhook_key/ \
  -H "Authorization: Bearer <token>"
```

### 3. Configure GitHub webhook

In your GitHub repository Settings > Webhooks:
- **Payload URL**: `https://forge.example.com/api/v2/eda_webhooks/github-deploy/`
- **Content type**: `application/json`
- **Secret**: The webhook key from step 2
- **Events**: Push events

### 4. Test with dry-run

```bash
curl -X POST https://forge.example.com/api/v2/event_rules/1/test/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "payload": {"ref": "refs/heads/main", "action": "push"},
    "headers": {}
  }'
```

---

## Frontend

The EDA UI is available in the **Automation** sidebar section:

- **Event Rules** (`/event_rules`) — Create, edit, enable/disable rules
- **Event Logs** (`/event_logs`) — View incoming webhooks and evaluation results
- **Outbound Webhooks** (`/outbound_webhooks`) — Configure job status push notifications

Each Event Rule detail page shows:
- Webhook URL (copy-to-clipboard)
- Webhook key (show/rotate)
- Condition and action configuration
- Recent event logs with status badges
- Dry-run test capability
