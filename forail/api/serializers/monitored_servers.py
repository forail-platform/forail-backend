from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from forail.api.serializers.base import BaseSerializer
from forail.main.models.monitored_server import MonitoredServer


class MonitoredServerSerializer(BaseSerializer):
    """A server that reports through ``forail-agent``.

    ``online`` and ``last_report_at`` come from the Forail Mobile backend, read
    once per request by the view; ``null`` means it could not be asked.
    """

    show_capabilities = ['edit', 'delete']

    online = serializers.SerializerMethodField()
    last_report_at = serializers.SerializerMethodField()

    class Meta:
        model = MonitoredServer
        fields = ('*', 'organization', 'owner', 'mobile_server_id', 'online', 'last_report_at')
        read_only_fields = ('owner', 'mobile_server_id')

    def get_related(self, obj):
        res = super().get_related(obj)
        res.update(
            organization=self.reverse('api:organization_detail', kwargs={'pk': obj.organization_id}),
            enrollment_code=self.reverse('api:monitored_server_enrollment_code', kwargs={'pk': obj.pk}),
            rotate_token=self.reverse('api:monitored_server_rotate_token', kwargs={'pk': obj.pk}),
            access_list=self.reverse('api:monitored_server_access_list', kwargs={'pk': obj.pk}),
            object_roles=self.reverse('api:monitored_server_object_roles_list', kwargs={'pk': obj.pk}),
            activity_stream=self.reverse('api:monitored_server_activity_stream_list', kwargs={'pk': obj.pk}),
        )
        if obj.owner_id:
            res['owner'] = self.reverse('api:user_detail', kwargs={'pk': obj.owner_id})
        return res

    def get_summary_fields(self, obj):
        summary = super().get_summary_fields(obj)
        if obj.owner_id:
            summary['owner'] = {'id': obj.owner.id, 'username': obj.owner.username, 'first_name': obj.owner.first_name, 'last_name': obj.owner.last_name}
        return summary

    def _status(self, obj):
        statuses = self.context.get('mobile_statuses')
        if statuses is None:
            return None
        return statuses.get(str(obj.mobile_server_id))

    def get_online(self, obj):
        status = self._status(obj)
        if self.context.get('mobile_statuses') is None:
            return None
        return bool(status and status.online)

    def get_last_report_at(self, obj):
        status = self._status(obj)
        return status.last_report_at if status else None

    def validate(self, attrs):
        if self.instance is not None:
            # The name is part of signed approvals on the phone and the server's
            # identity in the mobile backend; the organization decides who
            # manages it. Neither moves after registration.
            for field in ('name', 'organization'):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({field: _('Cannot be changed after the server is registered.')})
        return super().validate(attrs)


class EnrollmentCodeSerializer(serializers.Serializer):
    """A one-time code and the command that uses it. Never an agent token."""

    code = serializers.CharField(read_only=True)
    expires_at = serializers.CharField(read_only=True)
    api_url = serializers.CharField(read_only=True)
    command = serializers.CharField(read_only=True)
