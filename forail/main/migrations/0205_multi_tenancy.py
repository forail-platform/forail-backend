# Generated for Multi-Tenancy v1:
# Organization.tenant_* fields, TenantUsage, TenantQuotaEvent, TenantIsolationEvent.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0204_audit_event'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='is_tenant_root',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='organization',
            name='tenant_max_concurrent_jobs',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='tenant_max_daily_launches',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='tenant_max_hosts',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='tenant_max_storage_mb',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='tenant_isolation_strict',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='organization',
            name='tenant_logo_url',
            field=models.CharField(blank=True, default='', max_length=512),
        ),
        migrations.AddField(
            model_name='organization',
            name='tenant_primary_color',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddField(
            model_name='organization',
            name='tenant_secondary_color',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddField(
            model_name='organization',
            name='tenant_custom_domain',
            field=models.CharField(blank=True, db_index=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='organization',
            name='tenant_contact_email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.CreateModel(
            name='TenantUsage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('description', models.TextField(blank=True, default='')),
                ('concurrent_jobs_count', models.PositiveIntegerField(default=0)),
                ('launches_today_count', models.PositiveIntegerField(default=0)),
                ('launches_today_window_start', models.DateTimeField(blank=True, null=True)),
                ('hosts_count', models.PositiveIntegerField(default=0)),
                ('storage_mb_used', models.PositiveIntegerField(default=0)),
                ('last_recalculated_at', models.DateTimeField(blank=True, null=True)),
                ('organization', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='tenant_usage', to='main.organization')),
                ('created_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created+", to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('organization',),
                'app_label': 'main',
            },
        ),
        migrations.CreateModel(
            name='TenantQuotaEvent',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('description', models.TextField(blank=True, default='')),
                ('organization_name', models.CharField(blank=True, default='', max_length=512)),
                ('quota_kind', models.CharField(choices=[('concurrent_jobs', 'Concurrent jobs'), ('daily_launches', 'Daily launches'), ('hosts', 'Hosts'), ('storage_mb', 'Storage MB')], max_length=32)),
                ('decision', models.CharField(choices=[('allowed', 'Allowed'), ('blocked', 'Blocked')], max_length=16)),
                ('current_value', models.PositiveIntegerField(default=0)),
                ('limit_value', models.PositiveIntegerField(blank=True, null=True)),
                ('message', models.TextField(blank=True, default='')),
                ('organization', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tenant_quota_events', to='main.organization')),
                ('triggered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tenant_quota_events', to=settings.AUTH_USER_MODEL)),
                ('unified_job_template', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tenant_quota_events', to='main.unifiedjobtemplate')),
                ('created_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created+", to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created',),
                'app_label': 'main',
            },
        ),
        migrations.AddIndex(
            model_name='tenantquotaevent',
            index=models.Index(fields=['organization', '-created'], name='main_tenantqe_org_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantquotaevent',
            index=models.Index(fields=['decision', '-created'], name='main_tenantqe_dec_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantquotaevent',
            index=models.Index(fields=['quota_kind', '-created'], name='main_tenantqe_kind_idx'),
        ),
        migrations.CreateModel(
            name='TenantIsolationEvent',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('description', models.TextField(blank=True, default='')),
                ('resource_type', models.CharField(blank=True, default='', max_length=64)),
                ('resource_id', models.PositiveIntegerField(blank=True, null=True)),
                ('request_path', models.CharField(blank=True, default='', max_length=1024)),
                ('blocked', models.BooleanField(default=False)),
                ('accessed_organization', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tenant_isolation_events_as_accessed', to='main.organization')),
                ('user_organization', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tenant_isolation_events_as_user_org', to='main.organization')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tenant_isolation_events', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created+", to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created',),
                'app_label': 'main',
            },
        ),
        migrations.AddIndex(
            model_name='tenantisolationevent',
            index=models.Index(fields=['user', '-created'], name='main_tenantie_user_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantisolationevent',
            index=models.Index(fields=['user_organization', '-created'], name='main_tenantie_uorg_idx'),
        ),
    ]
