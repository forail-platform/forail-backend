# 17 — Self-Service Portal

End-user friendly catalog of curated automations with optional approval
workflow. Lets non-operator users (developers, app teams) request
existing Job Templates / Workflow Templates without direct AWX access,
and routes the request through approval before execution.

---

## Architecture

```
Admin curates a catalog item ────────────────┐
                                             │
                                             ▼
ServiceCatalogItem (wraps a JT or WFJT)      │
   ├── icon, category, tags                  │
   ├── requires_approval                     │
   └── approver_team (optional)              │
                                             │
                                             ▼
End user opens Service Portal, picks item, fills
multi-step dialog (justification → wf survey →
per-node surveys → confirm) and submits.

         │
         ▼
ServiceRequest.submit()
   │
   ├─ requires_approval=False ──► _launch() ──► JT/WFJT.create_unified_job()
   │                                          (status: running)
   │
   └─ requires_approval=True  ──► status: pending_approval
                                  approver inbox shows it
                                       │
                          ┌────────────┴────────────┐
                          ▼                         ▼
                 approve(user) ─► _launch()    reject(user, reason)
                                  status: running    status: rejected

         ▼
UnifiedJob runs to completion.
A post_save signal on UnifiedJob mirrors the terminal
status (successful/failed/canceled) back onto the linked
ServiceRequest via sync_status_from_job().
```

The portal sits on top of existing template execution machinery — there is
no duplication of launch logic. `_launch()` calls
`JobTemplate.create_unified_job()` / `WorkflowJobTemplate.create_unified_job()`
exactly the same way the standard `/launch/` endpoint does, including
honoring `node_survey_data` for workflows (which was added in the Workflow
Node Surveys feature).

---

## Models

`forail/main/models/service_catalog.py`

### `ServiceCatalogItem(CommonModelNameNotUnique)`

| Field                   | Notes                                                       |
| ----------------------- | ----------------------------------------------------------- |
| `organization`          | FK Organization (scopes visibility)                         |
| `name`                  | unique per org                                              |
| `description`           | free text                                                   |
| `icon`                  | lucide icon name shown in portal cards                      |
| `category`              | indexed; used for grouping/filtering                        |
| `tags`                  | JSON list, free-form                                        |
| `job_template`          | FK; **exactly one** of jt/wfjt set (validated in `clean()`) |
| `workflow_job_template` | FK; the other side                                          |
| `requires_approval`     | bool                                                        |
| `approver_team`         | FK Team; null = falls back to org admins                    |
| `enabled`               | bool; disabled items are hidden from portal                 |

Helper props: `underlying_template`, `is_workflow`.

### `ServiceRequest(CreatedModifiedModel)`

State machine:

```
              submit()
   created ──────────────┐
                         │
                         ▼
   pending_approval ─approve()─► approved ─_launch()─► running ─sync─► successful
        │                                                    │
        └─reject()─► rejected                                 ├─► failed
                                                              └─► canceled
```

Methods:

- `submit()` — entry point. If `requires_approval=False`, auto-approves and launches.
- `can_user_approve(user)` — superuser ✓ ; member of `approver_team` ✓ ; org admin (fallback when no team) ✓.
- `approve(user)` — checks status + perms, calls `_launch()`.
- `reject(user, reason)` — terminal `rejected` state.
- `_launch()` — calls `template.create_unified_job(extra_vars=…, node_survey_data=…)`, stores returned UJ, transitions to `running`, then `signal_start()`.
- `sync_status_from_job()` — invoked by post_save signal handler; mirrors UJ terminal status.

`TERMINAL_STATUSES = ('rejected', 'successful', 'failed', 'canceled')`

### Status propagation

A module-level `post_save` receiver in `service_catalog.py` listens for any
`UnifiedJob` save, filters to terminal statuses, finds linked
`ServiceRequest`s, and calls `sync_status_from_job()`. This works for both
`Job` and `WorkflowJob` without touching task code.

---

## Permissions & registration

`forail/main/models/__init__.py`:

- `permission_registry.register(..., ServiceCatalogItem)` — org-scoped RBAC
- `activity_stream_registrar.connect(ServiceCatalogItem)`
- `activity_stream_registrar.connect(ServiceRequest)`

End-users with read on the catalog item's organization can browse and submit;
approval requires `approver_team` membership or org admin.

---

## REST API

Mounted under `/api/v2/service_catalog_items/` and `/api/v2/service_requests/`.

### Catalog items

| Method | Path                                              | Purpose                                                                         |
| ------ | ------------------------------------------------- | ------------------------------------------------------------------------------- |
| GET    | `/api/v2/service_catalog_items/`                  | list (filters: `category`, `enabled`, `organization`, `search`)                 |
| POST   | `/api/v2/service_catalog_items/`                  | create                                                                          |
| GET    | `/api/v2/service_catalog_items/{id}/`             | detail                                                                          |
| PATCH  | `/api/v2/service_catalog_items/{id}/`             | update                                                                          |
| DELETE | `/api/v2/service_catalog_items/{id}/`             | delete                                                                          |
| GET    | `/api/v2/service_catalog_items/{id}/launch_data/` | merged survey spec from underlying JT/WFJT, plus per-node surveys for workflows |
| GET    | `/api/v2/service_catalog_items/{id}/requests/`    | requests for this item (admin)                                                  |
| POST   | `/api/v2/service_catalog_items/{id}/submit/`      | end-user submission entry point                                                 |

### Service requests

| Method | Path                                          | Purpose                                               |
| ------ | --------------------------------------------- | ----------------------------------------------------- |
| GET    | `/api/v2/service_requests/`                   | list (filters: `mine`, `status`, `catalog_item`)      |
| GET    | `/api/v2/service_requests/pending_approvals/` | approval inbox (filtered to caller's authority)       |
| GET    | `/api/v2/service_requests/{id}/`              | detail                                                |
| DELETE | `/api/v2/service_requests/{id}/`              | only allowed in `pending_approval` / `rejected` state |
| POST   | `/api/v2/service_requests/{id}/approve/`      | approve + launch                                      |
| POST   | `/api/v2/service_requests/{id}/reject/`       | reject (`{reason}`)                                   |

### Submit payload

```json
{
  "extra_vars": { "hostname": "web03" },
  "node_survey_data": {
    "deploy_node": { "version": "2.0" }
  },
  "justification": "nginx /health failing on web03"
}
```

`node_survey_data` is keyed by node `identifier` and used only for
workflow-backed catalog items.

### Launch data response

```json
{
  "catalog_item": { "id": 1, "name": "...", "requires_approval": true, ... },
  "is_workflow": true,
  "survey_enabled": true,
  "survey_spec": { "spec": [...] },
  "ask_variables_on_launch": false,
  "node_surveys": [
    { "node_id": 10, "identifier": "deploy", "survey_spec": { "spec": [...] } }
  ]
}
```

The frontend uses this to render the multi-step request dialog.

---

## Tests

`tests_standalone/test_service_catalog.py` (22 tests, no Django bootstrap):

- `submit()` with/without approval, launch failure → `failed`
- `can_user_approve` matrix: superuser, team member, non-member, org admin fallback, unauthenticated
- `approve()` / `reject()` permission checks and terminal-state guards
- `sync_status_from_job()` mapping for successful / failed / error / canceled / intermediate
- Workflow node_survey_data passthrough vs. JT-only path

Run with: `python -m unittest tests_standalone.test_service_catalog -v`
