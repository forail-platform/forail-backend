from django.test import RequestFactory
from django.urls import resolve


def _get(path):
    request = RequestFactory().get(path)
    response = resolve(path).func(request)
    if hasattr(response, 'render'):
        response.render()
    return response


def test_legacy_ui_index_sends_the_browser_to_the_frontend():
    response = _get('/ui_legacy/')
    assert response.status_code == 302
    assert response['Location'] == '/'


def test_upgrade_page_renders_while_migrations_are_pending():
    # The migration middleware redirects every request here until the
    # database is migrated, so this page must render with no static assets
    # and no database.
    response = _get('/ui_legacy/migrations_notran/')
    assert response.status_code == 200
    body = response.content.decode()
    assert 'data-cy="migration-message-upgrade"' in body
    assert 'is currently upgrading' in body
