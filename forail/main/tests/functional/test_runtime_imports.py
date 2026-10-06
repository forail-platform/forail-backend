"""Every third-party module Forail's own code imports must be installed.

Three features shipped dead because of this: EDA and drift imported
celery, outbound webhooks imported httpx, and WebAuthn's py_webauthn was in
requirements.in but missing from the compiled requirements.txt. Unit tests
did not notice because they stubbed or mocked the missing module. This
walks the source instead and asks the interpreter running the tests.
"""

import ast
import importlib.util
import os
import sys

import forail

# Imports that are deliberately optional or never run in the server process.
ALLOWED_MISSING = {
    'ansible_sign': 'playbooks/action_plugins run inside the execution environment',
    'gnupg': 'playbooks/action_plugins run inside the execution environment',
    'debug_toolbar': 'development settings only',
    'drf_yasg': 'schema generation, development only',
    'gprof2dot': 'profiling helper, optional',
    'logutils': 'imported by the handler only when that handler is configured',
    'thycotic': 'optional credential plugin, guarded',
    'celery': 'tenancy/queues.py guards it; Forail runs the AWX dispatcher, not Celery',
    'kombu': 'tenancy/queues.py guards it, as above',
    'defaults': 'settings modules imported relatively by name',
    'development': 'settings modules imported relatively by name',
}


def _third_party_imports():
    root = os.path.dirname(forail.__file__)
    found = {}
    for dirpath, _, files in os.walk(root):
        if os.sep + 'tests' in dirpath:
            continue
        for name in files:
            if not name.endswith('.py'):
                continue
            path = os.path.join(dirpath, name)
            try:
                tree = ast.parse(open(path).read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    modules = [node.module]
                else:
                    continue
                for module in modules:
                    top = module.split('.')[0]
                    if top != 'forail' and top not in sys.stdlib_module_names:
                        found.setdefault(top, set()).add(os.path.relpath(path, root))
    return found


def test_every_imported_package_is_installed():
    missing = {
        top: sorted(paths)
        for top, paths in _third_party_imports().items()
        if top not in ALLOWED_MISSING and importlib.util.find_spec(top) is None
    }
    assert not missing, 'imported but not installed: %s' % missing
