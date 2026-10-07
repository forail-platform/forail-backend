import pytest

from django.test import RequestFactory

from forail.sso.views import sso_complete, sso_error, sso_inactive


@pytest.fixture
def rf():
    return RequestFactory()


def _location(view, rf, cookie=None):
    request = rf.get('/sso/complete/')
    if cookie is not None:
        request.COOKIES['lastPath'] = cookie
    from django.contrib.auth.models import AnonymousUser

    request.user = AnonymousUser()
    response = view(request)
    assert response.status_code == 302
    return response['Location']


@pytest.mark.parametrize('view', [sso_complete, sso_error, sso_inactive])
def test_lands_on_the_frontend_not_the_legacy_ui(view, rf):
    assert _location(view, rf) == '/'


@pytest.mark.parametrize(
    'cookie, expected',
    [
        ('/jobs/12', '/jobs/12'),
        ('"/templates?page=2"', '/templates?page=2'),
        ('%2Finventories%2F3', '/inventories/3'),
    ],
)
def test_returns_to_the_last_path(rf, cookie, expected):
    assert _location(sso_complete, rf, cookie) == expected


@pytest.mark.parametrize(
    'cookie',
    ['//evil.example/', 'https://evil.example/', 'evil.example', '/\\evil.example', 'javascript:alert(1)', ''],
)
def test_last_path_cannot_redirect_off_site(rf, cookie):
    assert _location(sso_complete, rf, cookie) == '/'
