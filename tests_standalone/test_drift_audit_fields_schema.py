"""
Standalone schema test for DriftAlertRule audit fields.

Regression guard against a real outage: the original 0198_drift_models
migration built the `main_driftalertrule` table from the model definition
but did not materialize the `created_by` / `modified_by` ForeignKey
columns inherited from `PrimordialModel`. The model itself referenced
those fields (via Django's abstract base class), so any ORM query that
joined the audit columns — notably the cascade-delete chain triggered
by `DELETE /api/v2/organizations/{id}/` — exploded with

    psycopg.errors.UndefinedColumn:
    column main_driftalertrule.created_by_id does not exist

This test scans the migration history for every reference to
`driftalertrule` and asserts that *some* migration adds (or creates with)
the two audit columns. It deliberately avoids Django bootstrap so it
runs in seconds without a DB.
"""

import ast
import os
import re
import unittest

MIGRATIONS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'forail', 'main', 'migrations')
)


def _read_migrations():
    """Yield (filename, source) for every numbered migration file."""
    for fname in sorted(os.listdir(MIGRATIONS_DIR)):
        if not re.match(r'^\d{4}_', fname) or not fname.endswith('.py'):
            continue
        path = os.path.join(MIGRATIONS_DIR, fname)
        with open(path, encoding='utf-8') as fh:
            yield fname, fh.read()


def _migration_touches_field(source, model_name, field_name):
    """
    Return True if the migration source either creates `model_name`
    with `field_name` as one of its fields, or runs an AddField that
    targets (`model_name`, `field_name`). The check is intentionally
    string-based to avoid importing Django.
    """
    src = source

    # AddField hits — easiest case.
    addfield_re = re.compile(
        r"migrations\.AddField\(\s*model_name\s*=\s*['\"]"
        + re.escape(model_name.lower())
        + r"['\"]\s*,\s*name\s*=\s*['\"]"
        + re.escape(field_name)
        + r"['\"]",
        re.DOTALL,
    )
    if addfield_re.search(src):
        return True

    # CreateModel hits — the model block must mention field_name as a
    # tuple key inside its `fields=[...]` list. We use ast.parse so we
    # don't get fooled by comments / string literals elsewhere in the
    # file.
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Resolve dotted attribute like migrations.CreateModel.
        if not (isinstance(func, ast.Attribute) and func.attr == 'CreateModel'):
            continue
        name_kw = next((k for k in node.keywords if k.arg == 'name'), None)
        if name_kw is None or not isinstance(name_kw.value, ast.Constant):
            continue
        if name_kw.value.value.lower() != model_name.lower():
            continue
        fields_kw = next((k for k in node.keywords if k.arg == 'fields'), None)
        if fields_kw is None or not isinstance(fields_kw.value, ast.List):
            continue
        for tup in fields_kw.value.elts:
            if (
                isinstance(tup, ast.Tuple)
                and tup.elts
                and isinstance(tup.elts[0], ast.Constant)
                and tup.elts[0].value == field_name
            ):
                return True
    return False


class DriftAlertRuleAuditFieldsTest(unittest.TestCase):
    """The schema must include created_by / modified_by on driftalertrule."""

    def test_created_by_is_in_schema(self):
        migrations = list(_read_migrations())
        self.assertTrue(migrations, 'no migrations found — wrong path?')
        hits = [name for name, src in migrations
                if _migration_touches_field(src, 'driftalertrule', 'created_by')]
        self.assertTrue(
            hits,
            'No migration adds DriftAlertRule.created_by. The model inherits '
            'this FK from PrimordialModel but the column is missing in the DB '
            'schema, which breaks cascade-delete on Organization.',
        )

    def test_modified_by_is_in_schema(self):
        migrations = list(_read_migrations())
        hits = [name for name, src in migrations
                if _migration_touches_field(src, 'driftalertrule', 'modified_by')]
        self.assertTrue(
            hits,
            'No migration adds DriftAlertRule.modified_by. Same root cause '
            'as created_by — both FKs were declared on the abstract base '
            'class but not materialized in any concrete migration.',
        )


if __name__ == '__main__':
    unittest.main()
