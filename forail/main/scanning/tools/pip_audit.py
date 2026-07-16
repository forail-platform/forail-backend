"""pip-audit adapter.

Invoked as: pip-audit -r <requirements.txt> --format json
All findings are treated as severity='high' — pip-audit reports CVEs,
which for Forail's threat model are always significant.
"""

import json
import logging
import os

from forail.main.scanning.types import NormalizedFinding

TOOL_NAME = 'pip-audit'

logger = logging.getLogger('forail.main.scanning.tools.pip_audit')


def build_command(target_path, config):
    cmd = ['pip-audit', '--format', 'json']
    requirements = target_path
    if config and isinstance(config, dict):
        override = config.get('requirements')
        # L9: the admin-set requirements override is used as the -r path. Reject
        # ../ traversal so it can't be pointed outside the checkout (admin-only,
        # low impact, but no reason to leave the escape open).
        if override:
            if os.path.isabs(override) or '..' in override.replace('\\', '/').split('/'):
                logger.warning('pip-audit: ignoring unsafe requirements override %r', override)
            else:
                requirements = override
    cmd.extend(['-r', requirements])
    return cmd


def parse_output(stdout, stderr, returncode):
    """pip-audit JSON output:

    {
      "dependencies": [
        {"name": "urllib3", "version": "1.26.4",
         "vulns": [{"id": "GHSA-xxxx", "fix_versions": ["1.26.5"],
                    "description": "..."}]}
      ]
    }

    Older versions return a top-level list of dependency dicts.
    """
    findings = []
    if not stdout:
        return findings
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return findings

    if isinstance(data, dict):
        deps = data.get('dependencies') or []
    elif isinstance(data, list):
        deps = data
    else:
        return findings

    for dep in deps:
        if not isinstance(dep, dict):
            continue
        name = dep.get('name') or dep.get('package') or ''
        version = dep.get('version') or ''
        for v in dep.get('vulns') or []:
            if not isinstance(v, dict):
                continue
            rule_id = v.get('id') or ''
            description = v.get('description') or ''
            fix = v.get('fix_versions') or []
            msg = f'{name} {version}: {description}'
            if fix:
                msg += f' (fix: {", ".join(fix)})'
            findings.append(NormalizedFinding(
                rule_id=str(rule_id),
                severity='high',
                file_path=str(name),
                line=None,
                message=msg,
            ))
    return findings
