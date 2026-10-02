"""give_creator_permissions on models that exist only in the DAB RBAC."""

import pytest

from forail.main.models.policy import Policy
from forail.main.models.rbac import give_creator_permissions, has_legacy_roles


@pytest.mark.django_db
def test_creator_of_a_dab_only_model_gets_permissions_without_error(organization, org_admin):
    policy = Policy.objects.create(name='p', organization=organization)
    assert not has_legacy_roles(policy)
    # Used to raise AttributeError: 'Policy' object has no attribute 'creator_role'.
    give_creator_permissions(org_admin, policy)
    assert org_admin.has_obj_perm(policy, 'change')


@pytest.mark.django_db
def test_legacy_models_are_still_recognised(project, organization):
    assert has_legacy_roles(project)
    assert has_legacy_roles(organization)
