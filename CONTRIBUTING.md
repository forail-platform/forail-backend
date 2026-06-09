# Contributing to Forail Backend

Thanks for your interest in contributing!

The full contributing guide — git workflow, commit conventions, coding standards, PR process — lives in the [forail-deploy repository](https://github.com/forail-platform/forail-devops/blob/main/docs/10-contributing-guide.md). Please read it before submitting a pull request.

## Quick start (backend-specific)

```bash
git clone https://github.com/forail-platform/forail-backend.git
cd forail-backend
vagrant up
vagrant ssh -c "cd /vagrant && make develop"
```

See [README.md](./README.md) for full development setup.

## Backend-specific guidelines

- **Django migrations** — every model change needs a migration. Run `make makemigrations` inside the Vagrant VM. Never edit a merged migration.
- **Tests** — `make test` runs the suite. New features need test coverage; bug fixes need a regression test.
- **Settings** — never commit secrets. Use `forail/settings/development.py` for local overrides.
- **AWX heritage** — large parts of this codebase originate from Ansible AWX. When touching legacy code, preserve the existing architecture unless the change is explicitly a refactor.

## Reporting bugs

Open an issue with reproduction steps, expected vs. actual behavior, and your environment (Forail version, Python version, deployment method).

For security vulnerabilities, see [SECURITY.md](./SECURITY.md) — please do **not** open a public issue.
