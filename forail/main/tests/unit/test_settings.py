LOCAL_SETTINGS = (
    'ALLOWED_HOSTS',
    'BROADCAST_WEBSOCKET_PORT',
    'BROADCAST_WEBSOCKET_VERIFY_CERT',
    'BROADCAST_WEBSOCKET_PROTOCOL',
    'BROADCAST_WEBSOCKET_SECRET',
    'DATABASES',
    'CACHES',
    'DEBUG',
    'NAMED_URL_GRAPH',
)


def test_postprocess_auth_basic_enabled():
    from forail.settings import defaults

    assert 'forail.api.authentication.LoggedBasicAuthentication' in defaults.REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']


def test_default_settings():
    from django.conf import settings

    for k in dir(settings):
        if k not in settings.DEFAULTS_SNAPSHOT or k in LOCAL_SETTINGS:
            continue
        default_val = getattr(settings.default_settings, k, None)
        snapshot_val = settings.DEFAULTS_SNAPSHOT[k]
        assert default_val == snapshot_val, f'Setting for {k} does not match shapshot:\nsnapshot: {snapshot_val}\ndefault: {default_val}'
