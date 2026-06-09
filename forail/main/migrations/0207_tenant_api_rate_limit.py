"""Multi-Tenancy v2: per-tenant API rate limit field."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0206_rls_policies'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='tenant_api_rate_limit',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Max API requests per second for this tenant. NULL or 0 = unlimited.',
                null=True,
            ),
        ),
    ]
