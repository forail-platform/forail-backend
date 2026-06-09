import pytest


@pytest.mark.parametrize(
    "lib",
    [
        ("saml_pipeline"),
        ("social_pipeline"),
    ],
)
def test_module_loads(lib):
    module = __import__("forail.sso." + lib)  # noqa
