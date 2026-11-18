# Monitored servers (forail-mobile#52): the platform becomes the source of
# truth for which agent-reporting servers exist and who may reach them.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import forail.main.fields
import forail.main.models.monitored_server
from forail.main.migrations._dab_rbac import (
    create_permissions_as_operation,
    sync_managed_role_definitions,
)
from forail.main.tenancy.helpers import build_rls_policy_sql


def _rls_sql():
    # Same policy every other organization-owned table has (0211). Written out
    # for this one table so the migration does not depend on the list growing.
    create, drop = build_rls_policy_sql('main_monitoredserver', 'organization_id')
    return '\n'.join(
        [
            'ALTER TABLE main_monitoredserver ENABLE ROW LEVEL SECURITY;',
            'ALTER TABLE main_monitoredserver FORCE ROW LEVEL SECURITY;',
            drop,
            create,
        ]
    )


class Migration(migrations.Migration):
    dependencies = [
        ('main', '0212_activitystream_forail_models'),
        ('dab_rbac', '__first__'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MonitoredServer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(default=None, editable=False)),
                ('modified', models.DateTimeField(default=None, editable=False)),
                ('description', models.TextField(blank=True, default='')),
                (
                    'name',
                    models.CharField(max_length=63, validators=[forail.main.models.monitored_server.validate_server_name]),
                ),
                (
                    'mobile_server_id',
                    models.UUIDField(editable=False, help_text='The id of this server in the Forail Mobile backend.', unique=True),
                ),
                (
                    'created_by',
                    models.ForeignKey(
                        default=None,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='%(class)s_created+',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'modified_by',
                    models.ForeignKey(
                        default=None,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='%(class)s_modified+',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'organization',
                    models.ForeignKey(
                        help_text='The organization whose admins manage this server.',
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='monitored_servers',
                        to='main.organization',
                    ),
                ),
                (
                    'owner',
                    models.ForeignKey(
                        help_text='The user who registered the server.',
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='owned_monitored_servers',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'admin_role',
                    forail.main.fields.ImplicitRoleField(
                        editable=False,
                        null='True',
                        on_delete=django.db.models.deletion.SET_NULL,
                        parent_role=['singleton:system_administrator', 'organization.admin_role'],
                        related_name='+',
                        to='main.role',
                    ),
                ),
                (
                    'read_role',
                    forail.main.fields.ImplicitRoleField(
                        editable=False,
                        null='True',
                        on_delete=django.db.models.deletion.SET_NULL,
                        parent_role=['singleton:system_auditor', 'organization.auditor_role', 'admin_role'],
                        related_name='+',
                        to='main.role',
                    ),
                ),
            ],
            options={
                'ordering': ('organization__name', 'name'),
                'unique_together': {('organization', 'name')},
            },
        ),
        migrations.AddField(
            model_name='activitystream',
            name='monitored_server',
            field=models.ManyToManyField(blank=True, to='main.monitoredserver'),
        ),
        # DAB permissions for the new model, then the managed role definitions
        # that include them -- Organization Admin and Audit among them, which is
        # what lets an organization's admins reach its servers. Nothing is
        # deleted: setup_managed_role_definitions alone would drop the migrated
        # 'System Auditor' and every assignment of it.
        migrations.RunPython(create_permissions_as_operation, migrations.RunPython.noop),
        migrations.RunPython(sync_managed_role_definitions, migrations.RunPython.noop),
        migrations.RunSQL(sql=_rls_sql(), reverse_sql='ALTER TABLE main_monitoredserver DISABLE ROW LEVEL SECURITY;'),
    ]
