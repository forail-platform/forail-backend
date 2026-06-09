"""Audit Event serializers for the Forail API."""

from rest_framework import serializers

from forail.main.models.audit import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(read_only=True)

    class Meta:
        model = AuditEvent
        fields = [
            'id',
            'timestamp',
            'actor',
            'actor_username',
            'actor_ip',
            'actor_user_agent',
            'actor_session_id',
            'category',
            'severity',
            'action',
            'description',
            'resource_type',
            'resource_id',
            'resource_name',
            'action_node',
            'detail',
            'organization',
        ]
        read_only_fields = fields


class AuditEventSIEMSerializer(serializers.ModelSerializer):
    """
    Flat JSON format optimized for SIEM ingestion (Splunk, ELK, Datadog).
    All fields at top level, no nesting.
    """

    class Meta:
        model = AuditEvent
        fields = [
            'id',
            'timestamp',
            'actor_username',
            'actor_ip',
            'actor_user_agent',
            'actor_session_id',
            'category',
            'severity',
            'action',
            'description',
            'resource_type',
            'resource_id',
            'resource_name',
            'action_node',
            'detail',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Flatten detail dict into top-level keys with prefix
        detail = data.pop('detail', {})
        if detail and isinstance(detail, dict):
            for key, value in detail.items():
                data[f'detail_{key}'] = value
        # ISO format timestamp
        data['source'] = 'forail'
        data['event_type'] = f'{data["category"]}.{data["action"]}'
        return data
