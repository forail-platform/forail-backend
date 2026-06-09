# Security Policy

## Supported Versions

The latest released minor version receives security fixes. See [CHANGELOG.md](./CHANGELOG.md) for releases.

| Version | Supported |
|---------|-----------|
| 2026.05.x | Yes |
| < 2026.05 | No  |

## Reporting a Vulnerability

Please report security issues privately to **office@krletron.xyz**.

Do **not** open a public GitHub issue for suspected vulnerabilities.

Include:

- Component affected (API, task engine, SSO, etc.) and version
- Steps to reproduce, or proof-of-concept
- Impact assessment (data exposure, privilege escalation, denial of service, etc.)
- Suggested remediation if you have one

## Disclosure Timeline

- **48 hours** — acknowledgement of report
- **7 days** — initial assessment and severity classification
- **30 days** — fix released or mitigation provided for critical/high severity
- **90 days** — public disclosure after fix is available

We will credit you in the release notes unless you prefer to remain anonymous.

## Scope

In scope:

- forail-backend (this repository)
- Authentication, authorization, RBAC
- Task execution and Receptor mesh
- API endpoints and WebSocket channels

Out of scope:

- Issues in third-party dependencies (please report upstream)
- Self-inflicted misconfiguration (weak admin passwords, exposed admin port to public internet, etc.)
- Denial of service through resource exhaustion in development setups
