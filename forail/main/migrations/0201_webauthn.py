# Generated for OIDC + WebAuthn: WebAuthnCredential, challenges,
# Organization.webauthn_required.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0200_service_catalog'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='webauthn_required',
            field=models.CharField(
                choices=[('none', 'Not required'), ('admins', 'Required for admins only'), ('all', 'Required for all members')],
                default='none',
                help_text='Whether members of this organization must complete a WebAuthn assertion to finish login.',
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name='WebAuthnCredential',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('description', models.TextField(blank=True, default='')),
                ('credential_id', models.BinaryField(unique=True, help_text='Raw credential ID returned by the authenticator.')),
                ('public_key', models.BinaryField(help_text='COSE-encoded public key for assertion verification.')),
                ('sign_count', models.PositiveIntegerField(default=0, help_text='Authenticator signature counter — must monotonically increase.')),
                ('transports', models.JSONField(blank=True, default=list, help_text='List of advertised transports (usb, nfc, ble, internal, hybrid).')),
                ('aaguid', models.CharField(blank=True, default='', help_text='Authenticator AAGUID (UUID).', max_length=36)),
                ('label', models.CharField(blank=True, default='', help_text='User-facing nickname for this credential.', max_length=128)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('backup_eligible', models.BooleanField(default=False)),
                ('backup_state', models.BooleanField(default=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='webauthn_credentials', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created+", to=settings.AUTH_USER_MODEL)),
                ('modified_by', models.ForeignKey(default=None, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_modified+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created',),
                'app_label': 'main',
            },
        ),
        migrations.AddIndex(
            model_name='webauthncredential',
            index=models.Index(fields=['user', '-created'], name='main_webauthn_user_created_idx'),
        ),
        migrations.CreateModel(
            name='WebAuthnRegistrationChallenge',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('challenge', models.BinaryField(unique=True, help_text='Raw random bytes sent to the authenticator.')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='webauthn_registration_challenges', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created_at',),
                'app_label': 'main',
            },
        ),
        migrations.CreateModel(
            name='WebAuthnAuthenticationChallenge',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('challenge', models.BinaryField(unique=True, help_text='Raw random bytes sent to the authenticator.')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('user', models.ForeignKey(blank=True, help_text='Set when the user is known up-front (MFA), null for passwordless discovery.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='webauthn_auth_challenges', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created_at',),
                'app_label': 'main',
            },
        ),
    ]
