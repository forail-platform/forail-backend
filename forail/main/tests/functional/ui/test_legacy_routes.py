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


def test_upgrade_page_needs_no_static_files():
    body = _get('/ui_legacy/migrations_notran/').content.decode()
    assert '/static/' not in body
    assert 'pendo' not in body


def test_browsable_api_assets_are_collected_from_forail_static():
    from django.contrib.staticfiles import finders

    for asset in ('media/logo-header.svg', 'media/favicon.ico'):
        assert finders.find(asset), asset


def test_site_root_on_the_api_process_points_at_the_api():
    response = _get('/')
    assert response.status_code == 302
    assert response['Location'] == '/api/'


def test_frontend_routes_are_not_handled_by_the_api_process():
    # These used to fall into a catch-all that rendered index_forail.html,
    # a template that was never on any template path: a 500 for every
    # non-API URL that reached the backend directly.
    import pytest
    from django.urls import Resolver404

    for path in ('/jobs/12', '/templates/', '/some/frontend/route'):
        with pytest.raises(Resolver404):
            resolve(path)
