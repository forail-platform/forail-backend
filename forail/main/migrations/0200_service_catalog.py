# Generated for Self-Service Portal: ServiceCatalogItem, ServiceRequest

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0199_workflow_node_surveys'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceCatalogItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('description', models.TextField(blank=True, default='')),
                ('name', models.CharField(max_length=512)),
                ('icon', models.CharField(blank=True, default='', help_text='Lucide icon name shown in the portal card.', max_length=64)),
                ('category', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('tags', models.JSONField(blank=True, default=list, help_text='Free-form tags for filtering.')),
                ('requires_approval', models.BooleanField(default=False)),
                ('enabled', models.BooleanField(default=True)),
                ('created_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created+", to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified+", to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='service_catalog_items', to='main.organization')),
                ('job_template', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='service_catalog_items', to='main.jobtemplate')),
                ('workflow_job_template', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='service_catalog_items', to='main.workflowjobtemplate')),
                ('approver_team', models.ForeignKey(blank=True, help_text='Team allowed to approve requests. If null, falls back to org admins.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approvable_service_catalog_items', to='main.team')),
            ],
            options={
                'ordering': ('category', 'name'),
                'app_label': 'main',
                'unique_together': {('organization', 'name')},
            },
        ),
        migrations.AddIndex(
            model_name='servicecatalogitem',
            index=models.Index(fields=['category'], name='main_svccat_categor_idx'),
        ),
        migrations.AddIndex(
            model_name='servicecatalogitem',
            index=models.Index(fields=['enabled'], name='main_svccat_enabled_idx'),
        ),

        migrations.CreateModel(
            name='ServiceRequest',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('status', models.CharField(choices=[('pending_approval', 'Pending Approval'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('running', 'Running'), ('successful', 'Successful'), ('failed', 'Failed'), ('canceled', 'Canceled')], db_index=True, default='pending_approval', max_length=20)),
                ('extra_vars', models.JSONField(blank=True, default=dict)),
                ('node_survey_data', models.JSONField(blank=True, default=dict)),
                ('justification', models.TextField(blank=True, default='')),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('rejection_reason', models.TextField(blank=True, default='')),
                ('catalog_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='requests', to='main.servicecatalogitem')),
                ('requested_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='service_requests', to=settings.AUTH_USER_MODEL)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_service_requests', to=settings.AUTH_USER_MODEL)),
                ('unified_job', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='service_requests', to='main.unifiedjob')),
                ('created_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created+", to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created',),
                'app_label': 'main',
            },
        ),
        migrations.AddIndex(
            model_name='servicerequest',
            index=models.Index(fields=['status'], name='main_svcreq_status_idx'),
        ),
        migrations.AddIndex(
            model_name='servicerequest',
            index=models.Index(fields=['requested_by', '-created'], name='main_svcreq_user_created_idx'),
        ),
        migrations.AddIndex(
            model_name='servicerequest',
            index=models.Index(fields=['catalog_item', '-created'], name='main_svcreq_item_created_idx'),
        ),
    ]
