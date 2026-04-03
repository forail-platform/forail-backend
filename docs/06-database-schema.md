# 06 — Database Schema

Forge uses PostgreSQL 15. This document covers key tables, relationships,
maintenance, and useful queries for diagnostics.

---

## ER Diagram — Main Relationships

```
Organization ──1:N──► Project
             ──1:N──► Inventory ──1:N──► Host
             │                   ──1:N──► Group (M:N with Host)
             ──1:N──► Credential
             ──1:N──► JobTemplate ──1:N──► Job ──1:N──► JobEvent
             ──1:N──► Team ──M:N──► User
             ──1:N──► NotificationTemplate
             ──M:N──► InstanceGroup ──M:N──► Instance

WorkflowJobTemplate ──1:N──► WorkflowJobNode
Schedule ──► UnifiedJobTemplate (any template type)

Organization ──1:N──► EventRule ──1:N──► EventLog
             ──1:N──► OutboundWebhook

Role ──M:N──► User
     ──M:N──► Team
     ──parent/child──► Role (hierarchy)
```

---

## Key Tables

### Core Resources

| Table | Description | Growth rate |
|-------|-------------|-------------|
| `main_organization` | Tenant containers | Slow (1-10) |
| `auth_user` | User accounts | Slow (10-500) |
| `main_team` | User groups | Slow |
| `main_project` | Git repositories with playbooks | Slow |
| `main_inventory` | Host collections | Slow |
| `main_host` | Managed systems | Medium (10-10,000+) |
| `main_group` | Host groupings | Medium |
| `main_credential` | Encrypted secrets | Slow |
| `main_jobtemplate` | Templates for execution | Slow |

### Event-Driven Automation

| Table | Description | Growth rate |
|-------|-------------|-------------|
| `main_eventrule` | Webhook rules with conditions and actions | Slow (admin-created) |
| `main_eventlog` | Incoming webhook events and evaluation results | **Fast** (depends on webhook traffic) |
| `main_outboundwebhook` | Outbound webhook configurations | Slow |

### Execution (GROW FAST — cleanup required)

| Table | Description | Growth rate |
|-------|-------------|-------------|
| `main_job` | Execution records | **Fast** (100/day+) |
| `main_jobevent` | Output for every job (partitioned!) | **Very fast** (500K/day+) |
| `main_projectupdate` | Project sync records | Medium |
| `main_inventoryupdate` | Inventory sync records | Medium |
| `main_activitystream` | Audit log of all changes | **Fast** |
| `main_auditevent` | Immutable security audit log | **Fast** |
| `main_eventlog` | EDA webhook event logs | **Fast** (depends on webhook volume) |
| `main_notification` | Sent notifications | Medium |

### Watch out

- **`main_jobevent` is the largest table.** A single job with 100 hosts and 50 tasks generates
  ~5,000 rows. Without `cleanup_jobs`, this table can grow to hundreds of millions of rows.

- **Partitioning:** `main_jobevent` uses PostgreSQL list partitioning by `job_id`.
  Each job gets its own partition. A query for one job's events reads only one partition,
  not the entire table.

- **`main_activitystream` also grows fast.** Every create/update/delete on any
  model creates a record. Use `cleanup_activitystream --days=365` for cleanup.

---

## Polymorphic Models

Jobs use Django polymorphism — all types share a base table:

```
UnifiedJobTemplate (base table)
├── JobTemplate
├── Project
├── InventorySource
├── SystemJobTemplate
└── WorkflowJobTemplate

UnifiedJob (base table)
├── Job
├── ProjectUpdate
├── InventoryUpdate
├── AdHocCommand
├── SystemJob
└── WorkflowJob
```

The endpoint `/api/v2/unified_jobs/` shows ALL job types in a single list.

---

## Database Maintenance

### Backup

```bash
# Automated backup (uses the built-in script)
docker compose exec forge-task bash /etc/forge/backup.sh

# Manual backup
docker compose exec postgres pg_dump -U forge forge | gzip > backup_$(date +%Y%m%d).sql.gz
```

### Restore

```bash
# Stop the application
docker compose stop forge-web forge-task

# Restore
gunzip -c backup_20260310.sql.gz | docker compose exec -T postgres psql -U forge forge

# Restart
docker compose start forge-web forge-task
docker compose exec forge-web awx-manage migrate  # if version differs
```

### Cleanup (MANDATORY in production)

```bash
# Delete jobs older than 90 days (and their events/partitions)
forge-manage cleanup_jobs --days=90

# Delete activity stream older than one year
forge-manage cleanup_activitystream --days=365

# Delete expired sessions and tokens
forge-manage cleanup_sessions
forge-manage cleanup_tokens
```

**Recommendation:** Set up a System Job in the Forge UI that runs `cleanup_jobs` daily.

### Vacuum

```bash
# Reclaim dead tuples (run after large deletions)
docker compose exec postgres vacuumdb -U forge -z forge
```

### PostgreSQL Tuning for Forge

| Parameter | Recommendation | Why |
|-----------|---------------|-----|
| `shared_buffers` | 25% of RAM (e.g., 2GB) | Data cache |
| `effective_cache_size` | 75% of RAM (e.g., 6GB) | Query planner hint |
| `work_mem` | 64MB | Per-query memory for sort/join |
| `maintenance_work_mem` | 512MB | For VACUUM and CREATE INDEX |
| `random_page_cost` | 1.1 | For SSD storage |
| `log_min_duration_statement` | 1000 | Log queries > 1 second |

---

## Useful Diagnostic Queries

### System overview

```sql
SELECT
    (SELECT count(*) FROM main_organization) AS organizations,
    (SELECT count(*) FROM auth_user) AS users,
    (SELECT count(*) FROM main_host) AS hosts,
    (SELECT count(*) FROM main_jobtemplate) AS templates,
    (SELECT count(*) FROM main_job) AS jobs;
```

### Jobs by status (last 7 days)

```sql
SELECT status, count(*)
FROM main_job
WHERE created > NOW() - INTERVAL '7 days'
GROUP BY status ORDER BY count(*) DESC;
```

### Longest jobs (average by template)

```sql
SELECT jt.name, count(j.id) AS runs,
       round(avg(j.elapsed)::numeric, 1) AS avg_sec
FROM main_job j
JOIN main_jobtemplate jt ON j.job_template_id = jt.id
WHERE j.status = 'successful' AND j.created > NOW() - INTERVAL '30 days'
GROUP BY jt.name ORDER BY avg_sec DESC;
```

### Hosts with failures

```sql
SELECT h.name, i.name AS inventory
FROM main_host h
JOIN main_inventory i ON h.inventory_id = i.id
WHERE h.has_active_failures = true;
```

### Accessing the database

```bash
# Interactive shell
docker compose exec postgres psql -U forge forge

# Or through Django
docker compose exec forge-web awx-manage dbshell
```

---

## Migrations

Forge has **252 migrations** in `forge/main/migrations/`.

- All reference `forge.main.fields` (not `awx.main.fields`)
- The init script automatically runs `migrate` during deployment
- Never edit existing migrations — only add new ones
- Check status: `forge-manage showmigrations | grep "\[ \]"`
