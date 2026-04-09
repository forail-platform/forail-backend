"""ansible-lint adapter.

Invoked as: ansible-lint -f json --strict <playbook>
Native severity maps: warning -> low, error -> high.
"""

import json

from forge.main.scanning.types import NormalizedFinding

TOOL_NAME = 'ansible-lint'

_SEVERITY_MAP = {
    'warning': 'low',
    'error': 'high',
}


def build_command(target_path, config):
    cmd = ['ansible-lint', '-f', 'json']
    if config and isinstance(config, dict):
        if config.get('strict', True):
            cmd.append('--strict')
        profile = config.get('profile')
        if profile:
            cmd.extend(['--profile', str(profile)])
        for skip in config.get('skip_list', []) or []:
            cmd.extend(['--skip-list', str(skip)])
    else:
        cmd.append('--strict')
    cmd.append(target_path)
    return cmd


def _map_severity(raw):
    if not raw:
        return 'info'
    return _SEVERITY_MAP.get(str(raw).lower(), 'low')


def parse_output(stdout, stderr, returncode):
    """ansible-lint JSON output is a list of SARIF-ish objects:

    [
      {
        "type": "issue",
        "check_name": "yaml[line-length]",
        "categories": ["warning"],
        "severity": "warning",
        "message": "...",
        "location": {"path": "play.yml", "lines": {"begin": 12}}
      },
      ...
    ]

    Also tolerates the newer `{"issues": [...]}` envelope.
    """
    findings = []
    if not stdout:
        return findings
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return findings
    if isinstance(data, dict):
        items = data.get('issues') or data.get('results') or []
    elif isinstance(data, list):
        items = data
    else:
        return findings
    for item in items:
        if not isinstance(item, dict):
            continue
        rule_id = (item.get('check_name') or item.get('rule_id')
                   or (item.get('rule') or {}).get('id') or '')
        sev_raw = item.get('severity')
        if not sev_raw:
            cats = item.get('categories') or []
            sev_raw = cats[0] if cats else ''
        severity = _map_severity(sev_raw)
        loc = item.get('location') or {}
        file_path = loc.get('path') or item.get('filename') or ''
        lines = loc.get('lines') or {}
        line = None
        if isinstance(lines, dict):
            line = lines.get('begin') or lines.get('start')
        elif isinstance(lines, int):
            line = lines
        if line is None:
            line = item.get('line')
        try:
            line = int(line) if line is not None else None
        except (TypeError, ValueError):
            line = None
        message = item.get('message') or item.get('description') or ''
        findings.append(NormalizedFinding(
            rule_id=str(rule_id),
            severity=severity,
            file_path=str(file_path),
            line=line,
            message=str(message),
        ))
    return findings
