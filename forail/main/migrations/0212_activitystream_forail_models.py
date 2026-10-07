# Every model connected to the activity stream registrar needs a relation on
# ActivityStream named after it; these eight were connected without one, so
# saving any of them while the activity stream was enabled raised.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('main', '0211_rls_scoped_null_org'),
    ]

    operations = [
        migrations.AddField(model_name='activitystream', name='event_rule', field=models.ManyToManyField(blank=True, to='main.eventrule')),
        migrations.AddField(model_name='activitystream', name='outbound_webhook', field=models.ManyToManyField(blank=True, to='main.outboundwebhook')),
        migrations.AddField(model_name='activitystream', name='drift_alert_rule', field=models.ManyToManyField(blank=True, to='main.driftalertrule')),
        migrations.AddField(model_name='activitystream', name='service_catalog_item', field=models.ManyToManyField(blank=True, to='main.servicecatalogitem')),
        migrations.AddField(model_name='activitystream', name='service_request', field=models.ManyToManyField(blank=True, to='main.servicerequest')),
        migrations.AddField(model_name='activitystream', name='web_authn_credential', field=models.ManyToManyField(blank=True, to='main.webauthncredential')),
        migrations.AddField(model_name='activitystream', name='policy', field=models.ManyToManyField(blank=True, to='main.policy')),
        migrations.AddField(model_name='activitystream', name='scanner', field=models.ManyToManyField(blank=True, to='main.scanner')),
    ]
