from rest_framework import serializers


class RecommendationSerializer(serializers.Serializer):
    id = serializers.CharField()
    scope = serializers.CharField()
    severity = serializers.CharField()
    title = serializers.CharField()
    why = serializers.CharField()
    action_link = serializers.CharField()
