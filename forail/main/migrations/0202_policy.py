# Generated for Policy-as-Code: Policy, PolicyDecision,
# Organization.policy_enforcement.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0201_webauthn'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='policy_enforcement',
            field=models.CharField(
                choices=[('none', 'Disabled'), ('warn', 'Warn only'), ('enforce', 'Enforce — block on deny')],
                default='none',
                help_text='Per-organization Policy-as-Code enforcement mode.',
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name='Policy',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('description', models.TextField(blank=True, default='')),
                ('name', models.CharField(max_length=512)),
                ('rego_module', models.TextField(blank=True, default='', help_text='Full Rego source. Pushed to OPA on save.')),
                ('package_path', models.CharField(default='forail.launch', help_text='OPA data path that will be queried, e.g. "forail.launch".', max_length=255)),
                ('enforcement', models.CharField(choices=[('none', 'Disabled'), ('warn', 'Warn only'), ('enforce', 'Enforce — block on deny')], default='enforce', max_length=16)),
                ('enabled', models.BooleanField(default=True)),
                ('applies_to', models.JSONField(blank=True, default=list, help_text='Resource types this policy gates: job_template / workflow_job_template / ad_hoc_command. Empty = applies to all.')),
                ('trigger_count', models.PositiveIntegerField(default=0)),
                ('last_triggered_at', models.DateTimeField(blank=True, null=True)),
                ('last_evaluated_at', models.DateTimeField(blank=True, null=True)),
                ('last_sync_status', models.CharField(blank=True, default='', help_text='Status of the last push to OPA: ok / failed / pending.', max_length=32)),
                ('organization', models.ForeignKey(blank=True, help_text='If null, the policy is global across all organizations.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='policies', to='main.organization')),
                ('created_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created+", to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('name',),
                'app_label': 'main',
                'unique_together': {('organization', 'name')},
            },
        ),
        migrations.AddIndex(
            model_name='policy',
            index=models.Index(fields=['enabled'], name='main_policy_enabled_idx'),
        ),
        migrations.CreateModel(
            name='PolicyDecision',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('description', models.TextField(blank=True, default='')),
                ('policy_name', models.CharField(blank=True, default='', max_length=512)),
                ('decision', models.CharField(choices=[('allow', 'Allow'), ('warn', 'Warn'), ('deny', 'Deny')], db_index=True, max_length=8)),
                ('message', models.TextField(blank=True, default='')),
                ('context', models.JSONField(blank=True, default=dict)),
                ('policy', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='decisions', to='main.policy')),
                ('unified_job', models.ForeignKey(blank=True, help_text='Null when the launch was blocked before the job was kept.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='policy_decisions', to='main.unifiedjob')),
                ('unified_job_template', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='policy_decisions', to='main.unifiedjobtemplate')),
                ('organization', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.organization')),
                ('triggered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='policy_decisions', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created+", to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created',),
                'app_label': 'main',
            },
        ),
        migrations.AddIndex(
            model_name='policydecision',
            index=models.Index(fields=['decision', '-created'], name='main_policydec_decision_idx'),
        ),
        migrations.AddIndex(
            model_name='policydecision',
            index=models.Index(fields=['unified_job', '-created'], name='main_policydec_uj_idx'),
        ),
        migrations.AddIndex(
            model_name='policydecision',
            index=models.Index(fields=['policy', '-created'], name='main_policydec_policy_idx'),
        ),
    ]
