# 04 — Task Engine

The task engine manages the lifecycle of every job from launch to completion.
This is the most important part of the system — if you don't understand this,
you won't be able to diagnose job issues.

---

## Job Lifecycle

Every job goes through a defined state machine:

```
  Launch
    │
    ▼
 pending ──► waiting ──► running ──► successful
                                  ├── failed
                                  ├── error
                                  └── canceled
```

| Status | Meaning | Typical cause if stuck |
|--------|---------|------------------------|
| `pending` | In Celery queue, waiting for dispatcher | Redis is down or dispatcher crashed |
| `waiting` | Dispatcher has it, waiting for capacity | No free capacity on nodes |
| `running` | Ansible Runner is executing the playbook | Playbook takes a long time (normal) |
| `successful` | Playbook finished with exit code 0 | — |
| `failed` | Playbook finished with errors | Error in playbook or unreachable host |
| `error` | System error (not a playbook issue) | Problem with container, network, or receptor |
| `canceled` | User or system canceled it | Manual action or timeout |

---

## What Happens Step by Step

Jobs can be launched from multiple sources:
- **Manual:** User clicks "Launch" in the UI or calls `POST /api/v2/job_templates/{id}/launch/`
- **Schedule:** iCal recurrence rule triggers at the configured time
- **Webhook (legacy):** Direct webhook on a JobTemplate (GitHub/GitLab push triggers a specific template)
- **EDA Rule:** Event-Driven Automation rule fires after evaluating conditions on an incoming webhook (see `docs/15-event-driven-automation.md`)
- **Workflow:** A workflow node launches the job as part of a DAG execution

1. **Launch:** API creates a `Job` record in the database (status: `pending`), places a Celery task in Redis
2. **Dispatch:** Dispatcher reads the task from Redis, checks capacity, selects a node
3. **Execution:** Ansible Runner starts `ansible-playbook` with all parameters
4. **Events:** Every play/task/host result generates an event → Callback Receiver → database
5. **Real-time:** WSRelay sends events to WebSocket → browser updates UI
6. **Completion:** Runner finishes → job status is updated → notifications are sent

---

## Capacity — Why a Job Stays in "waiting"

Each node has a capacity calculated from CPU and memory:

```
CPU capacity  = CPU cores × 4 forks per core
RAM capacity  = RAM (MB) / 100 MB per fork
Effective     = whichever is smaller
```

**Example: 4-core machine with 8GB RAM**
- CPU: 4 × 4 = 16 forks
- RAM: 8192 / 100 = 81 forks
- Effective: 16 forks
- If 3 jobs are running with 5 forks each = 15 consumed, 1 remaining — next job waits

### Watch out

- **Forks:** Each job uses as many forks as defined on the template
  (default 5). Reducing forks on the template allows more concurrent jobs.

- **`list_instances`:** Use `forge-manage list_instances` to see capacity.
  If `remaining` = 0, jobs are waiting.

- **Instance Groups:** Organizations are mapped to instance groups. If an organization
  has only one group with one node, and that node is full — all jobs for that organization wait.

---

## Receptor Mesh

Receptor enables distributed job execution across multiple nodes.

### Node Types

| Type | Serves API | Runs jobs | When to use |
|------|-----------|-----------|-------------|
| `hybrid` | Yes | Yes | Single-node deployment (default) |
| `control` | Yes | No | Dedicated API server |
| `execution` | No | Yes | Dedicated job runner |
| `hop` | No | No | Relay for air-gapped networks |

### Watch out

- In a single-node deployment (default), Receptor runs locally and doesn't need configuration.
- Port 2222 (TCP) is used for inter-node communication. Must be open between nodes.
- The Receptor control socket is at `/var/run/awx-receptor/receptor.sock` — must be
  shared between the web and task containers.

---

## Event Processing

### Why job events matter

Job output is NOT one large text file. Every line/task/host result is a separate
`JobEvent` record in the database. This enables:
- Streaming output in real-time
- Filtering by host
- Searching within the output
- Efficient storage of large outputs

### Partitioned table

The `main_jobevent` table is partitioned by `job_id`. Each job gets its own partition.
Without this, a query for one job's events would scan millions of rows.

**Watch out:**
- Partitions are created automatically when a job starts
- `cleanup_jobs --days=90` drops old partitions
- **WITHOUT CLEANUP, THE DATABASE GROWS WITHOUT LIMIT** — this is the most common cause of full disk in production

---

## Task Container Processes

The task container runs 4 processes through `supervisord`:

| Process | What it does | If it goes down... |
|---------|-------------|-------------------|
| **Dispatcher** | Receives tasks from Redis, starts jobs | Jobs stay in `pending` |
| **Callback Receiver** | Receives events from Ansible Runner | Job output is empty |
| **WSRelay** | Sends events to WebSocket | UI doesn't update in real-time |
| **Receptor** | Mesh networking for remote execution | Remote jobs fail |

### Checking status

```bash
docker compose exec forge-task supervisorctl status
# All 4 processes must be RUNNING
```

---

## Execution Environments

An Execution Environment (EE) is a container image that contains everything needed
to run an Ansible playbook: Python, collections, modules, dependencies.

### Why EE?

Without an EE, the playbook uses Python and collections installed on the host. With an EE,
the playbook runs inside an isolated container with a precisely defined environment.
This guarantees reproducibility — the same playbook produces the same result regardless of the host.

### Watch out

- Every job template can reference a specific EE
- The `pull` option controls when the image is pulled: `always`, `missing`, `never`
- If the EE image doesn't exist locally and `pull=never`, the job will fail

---

## Troubleshooting

### Job stuck in "pending"

```bash
# 1. Is the dispatcher running?
docker compose exec forge-task supervisorctl status dispatcher

# 2. Is Redis running?
docker compose exec forge-task redis-cli -h redis ping

# 3. How many tasks are waiting in the queue?
docker compose exec redis redis-cli -n 0 LLEN celery
```

### Job stuck in "waiting"

```bash
# Check node capacity
docker compose exec forge-web awx-manage list_instances
# If remaining = 0, there's no free capacity
```

### Empty job output (no events)

```bash
# Check callback receiver
docker compose exec forge-task supervisorctl status callback_receiver
docker compose exec forge-task tail -f /var/log/supervisor/callback_receiver.log
```

### WebSocket not working (UI not updating)

```bash
# Check wsrelay and daphne processes
docker compose exec forge-task supervisorctl status wsrelay
docker compose exec forge-web supervisorctl status daphne

# Verify both containers have the same FORGE_BROADCAST_WEBSOCKET_SECRET
```

### Job finishes with "error" instead of "failed"

`error` means a system problem, not a playbook error. Check:
- Can Ansible Runner access the project (SCM sync)?
- Does the EE image exist?
- Does the Receptor socket exist (`/var/run/awx-receptor/receptor.sock`)?
- Logs: `docker compose logs forge-task | grep ERROR`
