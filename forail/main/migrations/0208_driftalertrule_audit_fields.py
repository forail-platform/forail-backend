"""Backfill `created_by` / `modified_by` FK columns on DriftAlertRule.

The 0198_drift_models migration created the DriftAlertRule table from the
model definition but omitted the two audit FKs inherited from
`PrimordialModel`. Django reads them from the abstract base but they were
never materialized in the schema, so any ORM query that joins those columns
(e.g. cascade-delete on Organization, which selects DriftAlertRule rows
to remove) fails with::

    psycopg.errors.UndefinedColumn: column main_driftalertrule.created_by_id
    does not exist

This migration adds both columns nullable + SET_NULL so existing rows are
unaffected.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0207_tenant_api_rate_limit'),
    ]

    operations = [
        migrations.AddField(
            model_name='driftalertrule',
            name='created_by',
            field=models.ForeignKey(
                default=None,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='%s(class)s_created+',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='driftalertrule',
            name='modified_by',
            field=models.ForeignKey(
                default=None,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='%s(class)s_modified+',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
