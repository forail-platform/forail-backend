# 12 — Configuration Reference

All settings: environment variables, Django settings, and database-backed settings.

---

## Environment Variables

Set in `tools/docker-compose-prod/.env`.

### Core (required)

| Variable                           | Description       | Generate with...            |
| ---------------------------------- | ----------------- | --------------------------- |
| `POSTGRES_PASSWORD`                | DB password       | `openssl rand -base64 24`   |
| `FORAIL_SECRET_KEY`                 | Django crypto key | `openssl rand -base64 32`   |
| `FORAIL_BROADCAST_WEBSOCKET_SECRET` | WS auth secret    | `openssl rand -base64 32`   |
| `FORAIL_ADMIN_PASSWORD`             | Admin password    | Manually — strong password  |
| `FORAIL_CSRF_TRUSTED_ORIGINS`       | CSRF origins      | `https://forail.example.com` |

### Optional

| Variable                | Default                | Description                        |
| ----------------------- | ---------------------- | ---------------------------------- |
| `FORAIL_IMAGE`           | `forail-platform/forail` | Docker image                       |
| `FORAIL_TAG`             | `latest`               | Image tag                          |
| `POSTGRES_USER`         | `forail`                | DB user                            |
| `POSTGRES_DB`           | `forail`                | DB name                            |
| `FORAIL_ADMIN_USER`      | `admin`                | Admin username                     |
| `FORAIL_ALLOWED_HOSTS`   | `*`                    | Allowed HTTP hosts                 |
| `FORAIL_NODE_NAME`       | `forail-node`           | Cluster node name                  |
| `FORAIL_NODE_TYPE`       | `hybrid`               | `hybrid` / `control` / `execution` |
| `NGINX_HTTP_PORT`       | `80`                   | HTTP port                          |
| `NGINX_HTTPS_PORT`      | `443`                  | HTTPS port                         |
| `SESSION_COOKIE_SECURE` | `True`                 | Cookie only over HTTPS             |
| `CSRF_COOKIE_SECURE`    | `True`                 | CSRF cookie only over HTTPS        |

### Watch out

- **`FORAIL_SECRET_KEY` — never change it** after deployment — it invalidates all sessions,
  tokens, and encrypted credentials.

- **`FORAIL_CSRF_TRUSTED_ORIGINS`** must be a **full URL with protocol**: `https://forail.example.com`.
  Hostname only without `https://` won't work.

- For **local development without HTTPS**, set `SESSION_COOKIE_SECURE=False` and `CSRF_COOKIE_SECURE=False`.

---

## Django Settings Files

Loaded in order (later ones override earlier):

```
1. forail/settings/defaults/*.py       ← Default values
2. forail/settings/production.py       ← Production override (DEBUG=False)
3. /etc/tower/settings.py             ← Root settings in the container
4. /etc/tower/conf.d/*.py             ← Per-module settings in the container
5. Database settings                  ← Runtime override via API
```

### Key default files

| File                       | What it controls                          |
| -------------------------- | ----------------------------------------- |
| `defaults/base.py`         | DATABASES, INSTALLED_APPS, REST_FRAMEWORK |
| `defaults/auth.py`         | Authentication backends                   |
| `defaults/jobs.py`         | Job execution defaults                    |
| `defaults/celery_conf.py`  | Celery/Redis                              |
| `defaults/logging_conf.py` | Logging levels and formats                |
| `production.py`            | DEBUG=False, ALLOWED_HOSTS, security      |

---

## Database-Backed Settings (changed without restart)

Access via API: `/api/v2/settings/`

### Job Settings (`/api/v2/settings/jobs/`)

| Setting                            | Default | Description                                        |
| ---------------------------------- | ------- | -------------------------------------------------- |
| `SCHEDULE_MAX_JOBS`                | `10`    | Max concurrent runs of the same scheduled template |
| `AWX_TASK_ENV`                     | `{}`    | Extra env variables for ALL playbook runs          |
| `DEFAULT_JOB_TIMEOUT`              | `0`     | Global job timeout in seconds (0 = no limit)       |
| `DEFAULT_INVENTORY_UPDATE_TIMEOUT` | `0`     | Inventory sync timeout                             |
| `DEFAULT_PROJECT_UPDATE_TIMEOUT`   | `0`     | Project sync timeout                               |
| `MAX_FORKS`                        | `200`   | Maximum forks per job                              |
| `AWX_ROLES_ENABLED`                | `True`  | Allow Ansible roles download                       |
| `AWX_COLLECTIONS_ENABLED`          | `True`  | Allow Ansible collections download                 |
| `PROJECT_UPDATE_VVV`               | `False` | Verbose project sync output                        |

### Auth Settings (`/api/v2/settings/authentication/`)

| Setting                           | Default | Description                              |
| --------------------------------- | ------- | ---------------------------------------- |
| `SESSION_COOKIE_AGE`              | `1800`  | Session timeout in seconds (30 min)      |
| `SESSIONS_PER_USER`               | `-1`    | Max concurrent sessions (-1 = unlimited) |
| `AUTH_BASIC_ENABLED`              | `True`  | Allow Basic auth for API                 |
| `ALLOW_OAUTH2_FOR_EXTERNAL_USERS` | `False` | SSO users can create tokens              |

### Logging Settings (`/api/v2/settings/logging/`)

| Setting                  | Default   | Description                                 |
| ------------------------ | --------- | ------------------------------------------- |
| `LOG_AGGREGATOR_HOST`    | `None`    | External log collector hostname             |
| `LOG_AGGREGATOR_PORT`    | `None`    | Port                                        |
| `LOG_AGGREGATOR_TYPE`    | `None`    | `logstash`, `splunk`, `loggly`, `sumologic` |
| `LOG_AGGREGATOR_ENABLED` | `False`   | Enable log forwarding                       |
| `LOG_AGGREGATOR_LEVEL`   | `WARNING` | Minimum level                               |

---

## Common Configuration Tasks

### Extend session to 8 hours

```bash
curl -u admin:password -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{"SESSION_COOKIE_AGE": 28800}' \
  https://forail.example.com/api/v2/settings/authentication/
```

### Set global job timeout to 1 hour

```bash
curl -u admin:password -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{"DEFAULT_JOB_TIMEOUT": 3600}' \
  https://forail.example.com/api/v2/settings/jobs/
```

### Add proxy for all jobs

```bash
curl -u admin:password -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{"AWX_TASK_ENV": {"HTTP_PROXY": "http://proxy:3128", "HTTPS_PROXY": "http://proxy:3128"}}' \
  https://forail.example.com/api/v2/settings/jobs/
```

### Disable Basic Auth (more secure)

```bash
curl -u admin:password -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{"AUTH_BASIC_ENABLED": false}' \
  https://forail.example.com/api/v2/settings/authentication/
```

### Send logs to Splunk

```bash
curl -u admin:password -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{
    "LOG_AGGREGATOR_HOST": "splunk.example.com",
    "LOG_AGGREGATOR_PORT": 8088,
    "LOG_AGGREGATOR_TYPE": "splunk",
    "LOG_AGGREGATOR_ENABLED": true
  }' \
  https://forail.example.com/api/v2/settings/logging/
```

### Configure LDAP

```bash
curl -u admin:password -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{
    "AUTH_LDAP_SERVER_URI": "ldaps://ldap.example.com:636",
    "AUTH_LDAP_BIND_DN": "cn=forail,ou=services,dc=example,dc=com",
    "AUTH_LDAP_BIND_PASSWORD": "LDAPPassword",
    "AUTH_LDAP_USER_SEARCH": ["ou=users,dc=example,dc=com", "SCOPE_SUBTREE", "(uid=%(user)s)"],
    "AUTH_LDAP_ORGANIZATION_MAP": {
      "Default": {"users": true, "remove_users": false}
    }
  }' \
  https://forail.example.com/api/v2/settings/ldap/
```

---

## Performance Tuning

### uWSGI Workers

```
processes = 5      # Default. Increase to 8-16 for high traffic.
harakiri = 120     # Worker timeout (seconds)
max-requests = 1000  # Restart worker after N requests
```

### Node Capacity

```
CPU capacity  = CPU cores × 4
RAM capacity  = RAM (MB) / 100
Effective     = whichever is smaller
```

**Example: 8 cores, 16GB RAM** → 32 forks → ~6 jobs with 5 forks each simultaneously

### Recommended Hardware

| Size                | CPU | RAM   | Disk      |
| ------------------- | --- | ----- | --------- |
| Small (≤100 hosts)  | 4   | 8GB   | 50GB SSD  |
| Medium (≤1000)      | 8   | 16GB  | 100GB SSD |
| Large (≤10000)      | 16  | 32GB  | 200GB SSD |
| Enterprise (10000+) | 16+ | 64GB+ | 500GB SSD |
