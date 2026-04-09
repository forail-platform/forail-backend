"""Checkov adapter.

Invoked as: checkov -f <playbook> --framework ansible -o json
Native severity maps: INFO/LOW/MEDIUM/HIGH/CRITICAL -> same (lowercased).
"""

import json

from forge.main.scanning.types import NormalizedFinding

TOOL_NAME = 'checkov'

_SEVERITY_MAP = {
    'info': 'info',
    'low': 'low',
    'medium': 'medium',
    'high': 'high',
    'critical': 'critical',
}


def build_command(target_path, config):
    framework = 'ansible'
    if config and isinstance(config, dict):
        framework = config.get('framework', 'ansible')
    cmd = ['checkov', '-f', target_path, '--framework', framework, '-o', 'json']
    if config and isinstance(config, dict):
        for skip in config.get('skip_check', []) or []:
            cmd.extend(['--skip-check', str(skip)])
    return cmd


def _map_severity(raw):
    if raw is None:
        return 'medium'
    return _SEVERITY_MAP.get(str(raw).lower(), 'medium')


def parse_output(stdout, stderr, returncode):
    """Checkov JSON output shape:

    {
      "results": {
        "failed_checks": [
          {"check_id": "CKV_ANSIBLE_1", "check_name": "...",
           "file_path": "play.yml", "file_line_range": [12, 15],
           "severity": "HIGH", "resource": "..."},
          ...
        ],
        "passed_checks": [...]
      }
    }

    Also tolerates a list-of-frameworks envelope.
    """
    findings = []
    if not stdout:
        return findings
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return findings

    if isinstance(data, list):
        envelopes = data
    else:
        envelopes = [data]

    for env in envelopes:
        if not isinstance(env, dict):
            continue
        results = env.get('results') or {}
        failed = results.get('failed_checks') or []
        for item in failed:
            if not isinstance(item, dict):
                continue
            rule_id = item.get('check_id') or item.get('bc_check_id') or ''
            severity = _map_severity(item.get('severity'))
            file_path = item.get('file_path') or item.get('repo_file_path') or ''
            line = None
            rng = item.get('file_line_range')
            if isinstance(rng, (list, tuple)) and rng:
                try:
                    line = int(rng[0])
                except (TypeError, ValueError):
                    line = None
            message = item.get('check_name') or item.get('description') or ''
            findings.append(NormalizedFinding(
                rule_id=str(rule_id),
                severity=severity,
                file_path=str(file_path),
                line=line,
                message=str(message),
            ))
    return findings
