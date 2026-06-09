# 19 — Policy-as-Code (OPA)

Runtime policy evaluation for launches. Forail stores Rego modules in
the database, pushes them to an OPA sidecar, and asks OPA before every
Job / WorkflowJob / AdHocCommand starts. OPA can return **allow**,
**warn**, or **deny**.

---

## Architecture

```
                    ┌────────────────────┐
   admin saves a    │  Policy.rego_module│
   Rego policy ────►│  + applies_to + ...│
                    └────────┬───────────┘
                             │ post_save signal
                             ▼
                    forail.main.policy.sync.push_policy()
                             │
                             │ PUT /v1/policies/forail_<id>
                             ▼
                    ┌────────────────────┐
                    │   forail-opa         │
                    │   (sidecar)         │
                    └────────────────────┘
                             ▲
                             │ POST /v1/data/<package_path>
                             │     {"input": <context>}
                             │
              ┌──────────────┴──────────────┐
              │  evaluate_launch(unified_job)│  hooked into:
              │                              │  - JobTemplateLaunch.post
              │                              │  - WorkflowJobTemplateLaunch.post
              │                              │  - AdHocCommandList.create
              └──────────────┬───────────────┘
                             │
                             ▼
                  parse_decision(result)
                  → (warns: list, denies: list)
                             │
              ┌──────────────┴──────────────┐
              │   PolicyDecisionResult       │
              │   .allowed / .warn_messages /│
              │   .deny_messages / .decisions│
              └──────────────┬───────────────┘
                             │
                  PolicyDecision rows persisted
                             │
              ┌──────────────┴───────────┐
              ▼                          ▼
          deny → 403 + delete UJ    warn → annotate UJ.job_explanation
                                             continue with signal_start
```

The hook is **strictly between** `create_unified_job(...)` and
`signal_start(...)`. By that point we know all of the launch context
(extra_vars, credentials, inventory) but the job has not yet been queued.
This is the smallest seam in the launch path that gives policy access
to the full request.

---

## Models

`forail/main/models/policy.py`

### `Policy(CommonModelNameNotUnique)`

| Field                                                     | Notes                                                                                                |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `organization`                                            | FK Organization (null = global)                                                                      |
| `rego_module`                                             | Full Rego source — pushed to OPA on save                                                             |
| `package_path`                                            | OPA Data path queried, e.g. `forail.launch`                                                           |
| `enforcement`                                             | `none` / `warn` / `enforce`                                                                          |
| `enabled`                                                 | bool                                                                                                 |
| `applies_to`                                              | JSON list of resource types (`job_template`, `workflow_job_template`, `ad_hoc_command`); empty = all |
| `trigger_count`, `last_triggered_at`, `last_evaluated_at` | populated by the evaluator                                                                           |
| `last_sync_status`                                        | `ok` / `failed` / blank — set by the post_save signal                                                |

`Organization.policy_enforcement` (`none/warn/enforce`, default `none`)
gates everything for the org.

### `PolicyDecision(CreatedModifiedModel)`

One row per policy hit (warn or deny). Stores `decision`, the cached
`policy_name` (so historical rows survive policy deletion), the
`unified_job` and `unified_job_template` references, the user that
triggered it, the human-readable `message`, and the full `context`
JSON used for the eval.

### Pure helpers

```python
effective_enforcement(global_enabled, org_enforcement, policy_enforcement)
fail_mode_decision(opa_unavailable, fail_mode)
```

Both are exported and unit-tested standalone.

---

## OPA client — `forail/main/policy/opa_client.py`

Tiny wrapper around `requests`. No extra dependency.

```python
upload_policy(server_url, policy_id, rego_module, timeout_ms)
delete_policy(server_url, policy_id, timeout_ms)
evaluate(server_url, package_path, input_doc, timeout_ms) -> result
parse_decision(result) -> (warns: list[str], denies: list[str])
```

`parse_decision` accepts every shape OPA might return:

- bare `bool` (`true` denies)
- bare `str` (deny message)
- list of strings or dicts (each entry = deny / warn-by-severity)
- dict with `warn` / `deny` lists
- dict with `violations: [{severity, message}, ...]`

Anything that doesn't match is treated as a silent allow.

---

## Sync — `forail/main/policy/sync.py`

`post_save` and `post_delete` signal receivers push or remove the Rego
text via OPA's `/v1/policies/forail_<policy_id>` endpoint. Failures
update `Policy.last_sync_status='failed'` but never raise — operators
see the failure in the list page.

The receivers are connected at module import time. Wired in
`forail/main/models/__init__.py`:

```python
import forail.main.policy.sync  # noqa: F401  -- registers signals
```

---

## Evaluator — `forail/main/policy/evaluator.py`

```python
build_launch_context(unified_job, request) -> dict
evaluate_launch(unified_job, request) -> PolicyDecisionResult
```

The context document shape:

```json
{
  "resource_type": "job_template",
  "resource_id": 42,
  "resource_name": "Restart nginx",
  "organization_id": 1,
  "organization_name": "Default",
  "user": { "id": 5, "username": "alice", "is_superuser": false },
  "extra_vars": { "hostname": "web01" },
  "inventory": { "id": 7, "name": "prod-web", "kind": "" },
  "credentials": [{ "id": 3, "name": "prod-ssh", "kind": "ssh" }],
  "playbook": "restart_nginx.yml",
  "now_iso": "2026-04-08T19:30:00Z",
  "client_ip": "10.0.0.42"
}
```

`evaluate_launch` is a no-op when:

- `OPA_ENABLED=False` globally, OR
- the job's organization has `policy_enforcement='none'`.

Otherwise it iterates `Policy.objects.filter(enabled=True)` whose
`applies_to` includes the resource type, evaluates each, and aggregates
the verdict. The org's enforcement value caps the per-policy mode:
an org in `warn` never blocks even if a policy is `enforce`.

---

## Settings — `forail/main/conf.py`

Registered under the **Security** category:

| Setting                     | Default                 | Notes                                                                            |
| --------------------------- | ----------------------- | -------------------------------------------------------------------------------- |
| `OPA_ENABLED`               | `False`                 | Master switch                                                                    |
| `OPA_SERVER_URL`            | `http://forail-opa:8181` | Base URL of the sidecar                                                          |
| `OPA_EVALUATION_TIMEOUT_MS` | `2000`                  | Per-evaluation timeout                                                           |
| `OPA_FAIL_MODE`             | `allow`                 | What happens when OPA is unreachable. `allow` = fail-open, `deny` = fail-closed. |

---

## REST API

Mounted under `/api/v2/policies/` and `/api/v2/policy_decisions/`.

| Method               | Path                             | Purpose                                                     |
| -------------------- | -------------------------------- | ----------------------------------------------------------- |
| GET / POST           | `/api/v2/policies/`              | List + create                                               |
| GET / PATCH / DELETE | `/api/v2/policies/{id}/`         | CRUD                                                        |
| POST                 | `/api/v2/policies/{id}/enable/`  | Enable                                                      |
| POST                 | `/api/v2/policies/{id}/disable/` | Disable                                                     |
| POST                 | `/api/v2/policies/{id}/test/`    | Dry-run with `{input}`                                      |
| GET                  | `/api/v2/policy_decisions/`      | List (filter: `decision`, `policy`, `unified_job`, `since`) |
| GET                  | `/api/v2/policy_decisions/{id}/` | Detail                                                      |

---

## Tests — `tests_standalone/test_policy.py`

19 standalone tests, no Django bootstrap (same pattern as
`test_drift.py`):

- `effective_enforcement` full matrix (global × org × policy).
- `fail_mode_decision` for OPA up/down × allow/deny mode.
- `parse_decision` for every supported shape: empty, bool, str, list,
  dict with warn/deny lists, dict with violations, dict with `deny: bool`.
- `applies_to_resource` matching.

Run with: `python -m unittest tests_standalone.test_policy -v`

---

## End-to-end manual verification

1. Add the OPA sidecar to compose (`forail-deploy/docker-compose.yml`,
   service `forail-opa`).
2. Settings → Security → set `OPA_ENABLED=true`,
   `OPA_SERVER_URL=http://forail-opa:8181`.
3. PATCH an organization's `policy_enforcement` to `enforce`.
4. Create a Policy via the UI: `applies_to=[job_template]`,
   `enforcement=enforce`, package `forail.launch`, body:

   ```rego
   package forail.launch
   default deny := false
   deny if {
     input.inventory.name == "prod-web"
     hour := time.parse_rfc3339_ns(input.now_iso) / 1e9 / 3600 % 24
     hour >= 18
   }
   ```

5. Try to launch a JT with the prod-web inventory after 18:00 → 403 +
   PolicyDecision row with decision `deny`.
6. Stop OPA, set `OPA_FAIL_MODE=deny`, retry → blocked with
   "OPA unavailable".
7. Switch to `OPA_FAIL_MODE=allow` → launches succeed but a warn
   PolicyDecision is logged for visibility.
