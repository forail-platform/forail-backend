# Generated for IaC Scanning & Supply Chain Security:
# Scanner, ScanResult, ScanFinding.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0202_policy'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Scanner',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('description', models.TextField(blank=True, default='')),
                ('name', models.CharField(max_length=512)),
                ('tool', models.CharField(choices=[('ansible-lint', 'ansible-lint'), ('checkov', 'Checkov'), ('pip-audit', 'pip-audit')], default='ansible-lint', max_length=32)),
                ('config', models.JSONField(blank=True, default=dict, help_text='Tool-specific configuration: rule excludes, profile, etc.')),
                ('severity_threshold', models.CharField(choices=[('info', 'Info'), ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')], default='high', max_length=16)),
                ('enforcement', models.CharField(choices=[('warn', 'Warn only'), ('enforce', 'Enforce — block on findings')], default='enforce', max_length=16)),
                ('enabled', models.BooleanField(default=True)),
                ('applies_to', models.JSONField(blank=True, default=list, help_text='Resource types this scanner gates: job_template / workflow_job_template / ad_hoc_command. Empty = applies to all.')),
                ('trigger_count', models.PositiveIntegerField(default=0)),
                ('last_run_at', models.DateTimeField(blank=True, null=True)),
                ('last_run_status', models.CharField(blank=True, default='', help_text='Status of the last scan: ok / warn / blocked / error / timeout.', max_length=32)),
                ('organization', models.ForeignKey(blank=True, help_text='If null, the scanner is global across all organizations.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='scanners', to='main.organization')),
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
            model_name='scanner',
            index=models.Index(fields=['enabled'], name='main_scanner_enabled_idx'),
        ),
        migrations.CreateModel(
            name='ScanResult',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('description', models.TextField(blank=True, default='')),
                ('scanner_name', models.CharField(blank=True, default='', max_length=512)),
                ('status', models.CharField(choices=[('ok', 'OK'), ('warn', 'Warn'), ('blocked', 'Blocked'), ('error', 'Error'), ('timeout', 'Timeout')], db_index=True, max_length=16)),
                ('duration_ms', models.PositiveIntegerField(default=0)),
                ('finding_count', models.PositiveIntegerField(default=0)),
                ('highest_severity', models.CharField(blank=True, default='', max_length=16)),
                ('message', models.TextField(blank=True, default='')),
                ('raw_output', models.TextField(blank=True, default='')),
                ('scanner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='results', to='main.scanner')),
                ('unified_job', models.ForeignKey(blank=True, help_text='Null when the launch was blocked before the job was kept.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scan_results', to='main.unifiedjob')),
                ('unified_job_template', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scan_results', to='main.unifiedjobtemplate')),
                ('organization', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.organization')),
                ('triggered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scan_results', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created+", to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created',),
                'app_label': 'main',
            },
        ),
        migrations.AddIndex(
            model_name='scanresult',
            index=models.Index(fields=['status', '-created'], name='main_scanres_status_idx'),
        ),
        migrations.AddIndex(
            model_name='scanresult',
            index=models.Index(fields=['unified_job', '-created'], name='main_scanres_uj_idx'),
        ),
        migrations.AddIndex(
            model_name='scanresult',
            index=models.Index(fields=['scanner', '-created'], name='main_scanres_scanner_idx'),
        ),
        migrations.CreateModel(
            name='ScanFinding',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rule_id', models.CharField(blank=True, default='', max_length=255)),
                ('severity', models.CharField(choices=[('info', 'Info'), ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')], default='info', max_length=16)),
                ('file_path', models.CharField(blank=True, default='', max_length=1024)),
                ('line', models.PositiveIntegerField(blank=True, null=True)),
                ('message', models.TextField(blank=True, default='')),
                ('scan_result', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='findings', to='main.scanresult')),
            ],
            options={
                'ordering': ('scan_result', 'id'),
                'app_label': 'main',
            },
        ),
        migrations.AddIndex(
            model_name='scanfinding',
            index=models.Index(fields=['scan_result', 'severity'], name='main_scanfind_sr_sev_idx'),
        ),
    ]
