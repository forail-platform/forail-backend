"""Scanner tool adapters. Each adapter exposes:

- TOOL_NAME: str
- build_command(target_path, config) -> list[str]
- parse_output(stdout, stderr, returncode) -> list[NormalizedFinding]
"""

from forge.main.scanning.tools import ansible_lint, checkov, pip_audit

ADAPTERS = {
    ansible_lint.TOOL_NAME: ansible_lint,
    checkov.TOOL_NAME: checkov,
    pip_audit.TOOL_NAME: pip_audit,
}


def get_adapter(tool_name):
    return ADAPTERS.get(tool_name)
