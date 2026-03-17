# Forge Backend

Django REST API + Task Engine for the Forge platform.

## Tech Stack

- Python 3.12
- Django 4.2.17
- Django REST Framework
- Celery 5
- PostgreSQL 15
- Redis 7
- Channels 4 (WebSocket)
- Receptor (distributed execution)

## Structure

```
forge/
├── api/          # REST API (DRF views, serializers, permissions)
├── main/         # Core models, signals, tasks, migrations
├── conf/         # Configuration and database-backed settings
├── sso/          # SSO integration (LDAP, SAML, Social Auth)
├── settings/     # Django settings (development, production)
├── playbooks/    # Ansible playbooks for job execution
├── locale/       # Internationalization
└── ui/           # Legacy UI (awx compatibility)
```

## Development

```bash
# Vagrant VM (required for development)
vagrant up
vagrant ssh

# Run tests
pytest forge/main/tests/unit/ -v
pytest forge/main/tests/functional/ -v

# Lint
flake8
```

## API

Base URL: `/api/v2/`

See [docs/11-api-reference.md](docs/11-api-reference.md) for the complete reference.

## Documentation

- [Backend Django](docs/02-backend-django.md)
- [Task Engine](docs/04-task-engine.md)
- [Authentication & RBAC](docs/05-authentication-rbac.md)
- [Database Schema](docs/06-database-schema.md)
- [Testing Guide](docs/09-testing-guide.md)
- [API Reference](docs/11-api-reference.md)
- [Configuration Reference](docs/12-configuration-reference.md)

## Docker

```bash
docker build -t krlex/forge-backend:latest .
```

## Related Repositories

- [forge-frontend](https://git.cloudforyour.work/forge-platform/forge-frontend) — React UI
- [forge-devops](https://git.cloudforyour.work/forge-platform/forge-devops) — Docker Compose, Nginx, CI/CD
