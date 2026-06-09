# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.utils.translation import gettext_lazy as _

from oauth2_provider.models import get_access_token_model

from forail.api.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    SubListAPIView,
    SubListCreateAPIView,
)
from forail.api import serializers
from forail.main import models


class OAuth2ApplicationList(ListCreateAPIView):
    name = _("OAuth 2 Applications")

    model = models.OAuth2Application
    serializer_class = serializers.OAuth2ApplicationSerializer
    swagger_topic = 'Authentication'


class OAuth2ApplicationDetail(RetrieveUpdateDestroyAPIView):
    name = _("OAuth 2 Application Detail")

    model = models.OAuth2Application
    serializer_class = serializers.OAuth2ApplicationSerializer
    swagger_topic = 'Authentication'

    def update_raw_data(self, data):
        data.pop('client_secret', None)
        return super(OAuth2ApplicationDetail, self).update_raw_data(data)


class ApplicationOAuth2TokenList(SubListCreateAPIView):
    name = _("OAuth 2 Application Tokens")

    model = models.OAuth2AccessToken
    serializer_class = serializers.OAuth2TokenSerializer
    parent_model = models.OAuth2Application
    relationship = 'oauth2accesstoken_set'
    parent_key = 'application'
    swagger_topic = 'Authentication'


class OAuth2ApplicationActivityStreamList(SubListAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
    parent_model = models.OAuth2Application
    relationship = 'activitystream_set'
    swagger_topic = 'Authentication'
    search_fields = ('changes',)


class OAuth2TokenList(ListCreateAPIView):
    name = _("OAuth2 Tokens")

    model = models.OAuth2AccessToken
    serializer_class = serializers.OAuth2TokenSerializer
    swagger_topic = 'Authentication'


class OAuth2UserTokenList(SubListCreateAPIView):
    name = _("OAuth2 User Tokens")

    model = models.OAuth2AccessToken
    serializer_class = serializers.OAuth2TokenSerializer
    parent_model = models.User
    relationship = 'main_oauth2accesstoken'
    parent_key = 'user'
    swagger_topic = 'Authentication'


class UserAuthorizedTokenList(SubListCreateAPIView):
    name = _("OAuth2 User Authorized Access Tokens")

    model = models.OAuth2AccessToken
    serializer_class = serializers.UserAuthorizedTokenSerializer
    parent_model = models.User
    relationship = 'oauth2accesstoken_set'
    parent_key = 'user'
    swagger_topic = 'Authentication'

    def get_queryset(self):
        return get_access_token_model().objects.filter(application__isnull=False, user=self.request.user)


class OrganizationApplicationList(SubListCreateAPIView):
    name = _("Organization OAuth2 Applications")

    model = models.OAuth2Application
    serializer_class = serializers.OAuth2ApplicationSerializer
    parent_model = models.Organization
    relationship = 'applications'
    parent_key = 'organization'
    swagger_topic = 'Authentication'


class UserPersonalTokenList(SubListCreateAPIView):
    name = _("OAuth2 Personal Access Tokens")

    model = models.OAuth2AccessToken
    serializer_class = serializers.UserPersonalTokenSerializer
    parent_model = models.User
    relationship = 'main_oauth2accesstoken'
    parent_key = 'user'
    swagger_topic = 'Authentication'

    def get_queryset(self):
        return get_access_token_model().objects.filter(application__isnull=True, user=self.request.user)


class OAuth2TokenDetail(RetrieveUpdateDestroyAPIView):
    name = _("OAuth Token Detail")

    model = models.OAuth2AccessToken
    serializer_class = serializers.OAuth2TokenDetailSerializer
    swagger_topic = 'Authentication'


class OAuth2TokenActivityStreamList(SubListAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
    parent_model = models.OAuth2AccessToken
    relationship = 'activitystream_set'
    swagger_topic = 'Authentication'
    search_fields = ('changes',)
