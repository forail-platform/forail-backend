# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# ASGI, channels, and broadcast websocket settings

from .celery_conf import BROKER_URL

ASGI_APPLICATION = "forail.main.routing.application"

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [BROKER_URL], "capacity": 10000, "group_expiry": 157784760}}  # 5 years
}

# Secret header value to exchange for websockets responsible for distributing websocket messages.
# This needs to be kept secret and randomly generated
BROADCAST_WEBSOCKET_SECRET = ''

# Port for broadcast websockets to connect to
# Note: that the clients will follow redirect responses
BROADCAST_WEBSOCKET_PORT = 443

# Whether or not broadcast websockets should check nginx certs when interconnecting
BROADCAST_WEBSOCKET_VERIFY_CERT = False

# Connect to other AWX nodes using http or https
BROADCAST_WEBSOCKET_PROTOCOL = 'https'

# All websockets that connect to the broadcast websocket endpoint will be put into this group
BROADCAST_WEBSOCKET_GROUP_NAME = 'broadcast-group_send'

# Time wait before retrying connecting to a websocket broadcast tower node
BROADCAST_WEBSOCKET_RECONNECT_RETRY_RATE_SECONDS = 5

# How often websocket process will look for changes in the Instance table
BROADCAST_WEBSOCKET_NEW_INSTANCE_POLL_RATE_SECONDS = 10

# How often websocket process will generate stats
BROADCAST_WEBSOCKET_STATS_POLL_RATE_SECONDS = 5

# How often should web instances advertise themselves?
BROADCAST_WEBSOCKET_BEACON_FROM_WEB_RATE_SECONDS = 15

DJANGO_GUID = {'GUID_HEADER_NAME': 'X-API-Request-Id'}
