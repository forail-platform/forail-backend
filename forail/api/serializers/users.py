# Copyright (c) 2015 Ansible, Inc.
# Copyright (c) 2026 Krstan Vjestica / Forail Project
# All Rights Reserved.

"""User serializers for the Forail API."""

# Django
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.utils.translation import gettext_lazy as _

# Django REST Framework
from rest_framework import serializers

# AWX
from forail.api.serializers.base import BaseSerializer
from forail.sso.common import get_external_account


class UserSerializer(BaseSerializer):
    password = serializers.CharField(required=False, default='', help_text=_('Field used to change the password.'))
    ldap_dn = serializers.CharField(source='profile.ldap_dn', read_only=True)
    external_account = serializers.SerializerMethodField(help_text=_('Set if the account is managed by an external service'))
    is_system_auditor = serializers.BooleanField(default=False)
    show_capabilities = ['edit', 'delete']

    class Meta:
        model = User
        fields = (
            '*',
            '-name',
            '-description',
            'username',
            'first_name',
            'last_name',
            'email',
            'is_superuser',
            'is_system_auditor',
            'password',
            'ldap_dn',
            'last_login',
            'external_account',
        )
        extra_kwargs = {'last_login': {'read_only': True}}

    def to_representation(self, obj):
        ret = super(UserSerializer, self).to_representation(obj)
        if self.get_external_account(obj):
            ret.pop('password', None)
        else:
            ret['password'] = '$encrypted$'
        if obj and type(self) is UserSerializer:
            ret['auth'] = obj.social_auth.values('provider', 'uid')
        return ret

    def get_validation_exclusions(self, obj=None):
        ret = super(UserSerializer, self).get_validation_exclusions(obj)
        ret.extend(['password', 'is_system_auditor'])
        return ret

    def validate_password(self, value):
        django_validate_password(value)
        if not self.instance and value in (None, ''):
            raise serializers.ValidationError(_('Password required for new User.'))

        password_max_length = User._meta.get_field('password').max_length
        if len(value) > password_max_length:
            raise serializers.ValidationError(_('Password max length is {}'.format(password_max_length)))
        if getattr(settings, 'LOCAL_PASSWORD_MIN_LENGTH', 0) and len(value) < getattr(settings, 'LOCAL_PASSWORD_MIN_LENGTH'):
            raise serializers.ValidationError(_('Password must be at least {} characters long.'.format(getattr(settings, 'LOCAL_PASSWORD_MIN_LENGTH'))))
        if getattr(settings, 'LOCAL_PASSWORD_MIN_DIGITS', 0) and sum(c.isdigit() for c in value) < getattr(settings, 'LOCAL_PASSWORD_MIN_DIGITS'):
            raise serializers.ValidationError(_('Password must contain at least {} digits.'.format(getattr(settings, 'LOCAL_PASSWORD_MIN_DIGITS'))))
        if getattr(settings, 'LOCAL_PASSWORD_MIN_UPPER', 0) and sum(c.isupper() for c in value) < getattr(settings, 'LOCAL_PASSWORD_MIN_UPPER'):
            raise serializers.ValidationError(
                _('Password must contain at least {} uppercase characters.'.format(getattr(settings, 'LOCAL_PASSWORD_MIN_UPPER')))
            )
        if getattr(settings, 'LOCAL_PASSWORD_MIN_SPECIAL', 0) and sum(not c.isalnum() for c in value) < getattr(settings, 'LOCAL_PASSWORD_MIN_SPECIAL'):
            raise serializers.ValidationError(
                _('Password must contain at least {} special characters.'.format(getattr(settings, 'LOCAL_PASSWORD_MIN_SPECIAL')))
            )

        return value

    def _update_password(self, obj, new_password):
        if new_password and new_password != '$encrypted$' and not self.get_external_account(obj):
            obj.set_password(new_password)
            obj.save(update_fields=['password'])
            update_session_auth_hash(self.context['request'], obj)
        elif not obj.password:
            obj.set_unusable_password()
            obj.save(update_fields=['password'])

    def get_external_account(self, obj):
        return get_external_account(obj)

    def create(self, validated_data):
        new_password = validated_data.pop('password', None)
        is_system_auditor = validated_data.pop('is_system_auditor', None)
        obj = super(UserSerializer, self).create(validated_data)
        self._update_password(obj, new_password)
        if is_system_auditor is not None:
            obj.is_system_auditor = is_system_auditor
        return obj

    def update(self, obj, validated_data):
        new_password = validated_data.pop('password', None)
        is_system_auditor = validated_data.pop('is_system_auditor', None)
        obj = super(UserSerializer, self).update(obj, validated_data)
        self._update_password(obj, new_password)
        if is_system_auditor is not None:
            obj.is_system_auditor = is_system_auditor
        return obj

    def get_related(self, obj):
        res = super(UserSerializer, self).get_related(obj)
        res.update(
            dict(
                teams=self.reverse('api:user_teams_list', kwargs={'pk': obj.pk}),
                organizations=self.reverse('api:user_organizations_list', kwargs={'pk': obj.pk}),
                admin_of_organizations=self.reverse('api:user_admin_of_organizations_list', kwargs={'pk': obj.pk}),
                projects=self.reverse('api:user_projects_list', kwargs={'pk': obj.pk}),
                credentials=self.reverse('api:user_credentials_list', kwargs={'pk': obj.pk}),
                roles=self.reverse('api:user_roles_list', kwargs={'pk': obj.pk}),
                activity_stream=self.reverse('api:user_activity_stream_list', kwargs={'pk': obj.pk}),
                access_list=self.reverse('api:user_access_list', kwargs={'pk': obj.pk}),
                tokens=self.reverse('api:o_auth2_token_list', kwargs={'pk': obj.pk}),
                authorized_tokens=self.reverse('api:user_authorized_token_list', kwargs={'pk': obj.pk}),
                personal_tokens=self.reverse('api:user_personal_token_list', kwargs={'pk': obj.pk}),
            )
        )
        return res

    def _validate_ldap_managed_field(self, value, field_name):
        if not getattr(settings, 'AUTH_LDAP_SERVER_URI', None):
            return value
        try:
            is_ldap_user = bool(self.instance and self.instance.profile.ldap_dn)
        except AttributeError:
            is_ldap_user = False
        if is_ldap_user:
            ldap_managed_fields = ['username']
            ldap_managed_fields.extend(getattr(settings, 'AUTH_LDAP_USER_ATTR_MAP', {}).keys())
            ldap_managed_fields.extend(getattr(settings, 'AUTH_LDAP_USER_FLAGS_BY_GROUP', {}).keys())
            if field_name in ldap_managed_fields:
                if value != getattr(self.instance, field_name):
                    raise serializers.ValidationError(_('Unable to change %s on user managed by LDAP.') % field_name)
        return value

    def validate_username(self, value):
        return self._validate_ldap_managed_field(value, 'username')

    def validate_first_name(self, value):
        return self._validate_ldap_managed_field(value, 'first_name')

    def validate_last_name(self, value):
        return self._validate_ldap_managed_field(value, 'last_name')

    def validate_email(self, value):
        return self._validate_ldap_managed_field(value, 'email')

    def validate_is_superuser(self, value):
        return self._validate_ldap_managed_field(value, 'is_superuser')


class UserActivityStreamSerializer(UserSerializer):
    """Changes to system auditor status are shown as separate entries,
    so by excluding it from fields here we avoid duplication, which
    would carry some unintended consequences.
    """

    class Meta:
        model = User
        fields = ('*', '-is_system_auditor')
