"""Add AuditEvent model and ActivityStream audit fields."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('main', '0203_scanner'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditEvent',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor_username', models.CharField(blank=True, default='', help_text='Denormalized username, preserved after user deletion.', max_length=150)),
                ('actor_ip', models.GenericIPAddressField(blank=True, help_text='IP address of the actor.', null=True)),
                ('actor_user_agent', models.CharField(blank=True, default='', max_length=512)),
                ('actor_session_id', models.CharField(blank=True, default='', max_length=64)),
                ('category', models.CharField(choices=[('auth', 'Authentication'), ('credential_access', 'Credential Access'), ('permission_change', 'Permission Change'), ('resource_change', 'Resource Change'), ('system', 'System Event')], db_index=True, max_length=32)),
                ('severity', models.CharField(choices=[('info', 'Info'), ('warning', 'Warning'), ('critical', 'Critical')], default='info', max_length=16)),
                ('action', models.CharField(db_index=True, help_text="Action performed, e.g. 'login', 'credential_used', 'role_granted'.", max_length=128)),
                ('description', models.TextField(blank=True, default='', help_text='Human-readable description of the event.')),
                ('resource_type', models.CharField(blank=True, db_index=True, default='', help_text="Type of resource affected, e.g. 'credential', 'job_template'.", max_length=128)),
                ('resource_id', models.IntegerField(blank=True, help_text='ID of the affected resource.', null=True)),
                ('resource_name', models.CharField(blank=True, default='', help_text='Name of the affected resource at the time of the event.', max_length=512)),
                ('action_node', models.CharField(blank=True, default='', help_text='Cluster node where the event occurred.', max_length=512)),
                ('detail', models.JSONField(blank=True, default=dict, help_text='Additional structured data for the event.')),
                ('actor', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_events', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_events', to='main.organization')),
            ],
            options={
                'ordering': ('-timestamp',),
            },
        ),
        # ActivityStream audit fields (actor_ip, actor_user_agent, actor_session_id)
        migrations.AddField(
            model_name='activitystream',
            name='actor_ip',
            field=models.GenericIPAddressField(blank=True, help_text='IP address of the actor who triggered this event.', null=True),
        ),
        migrations.AddField(
            model_name='activitystream',
            name='actor_user_agent',
            field=models.CharField(blank=True, default='', help_text="User-Agent header from the actor's request.", max_length=512),
        ),
        migrations.AddField(
            model_name='activitystream',
            name='actor_session_id',
            field=models.CharField(blank=True, default='', help_text='Session ID of the actor at the time of the event.', max_length=64),
        ),
    ]
