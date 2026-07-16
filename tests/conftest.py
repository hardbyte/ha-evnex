"""Shared fixtures for evnex integration tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pycognito.exceptions import SoftwareTokenMFAChallengeException

pytest_plugins = "pytest_homeassistant_custom_component"

USER_ID = "4c8aea03-56bf-47e7-9e7a-383a00793420"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def make_user_detail(name="Test User"):
    user = MagicMock()
    user.id = USER_ID
    user.name = name
    user.email = "user@example.com"
    user.organisations = []
    return user


@pytest.fixture
def mock_evnex_client():
    """A mocked Evnex client that authenticates without MFA."""
    client = MagicMock()
    client.authenticate = MagicMock()
    client.respond_to_mfa_challenge = MagicMock()
    client.get_user_detail = AsyncMock(return_value=make_user_detail())
    client.org_id = "org-1"
    client.id_token = "id-0"
    client.access_token = "access-0"
    client.refresh_token = "refresh-0"
    return client


@pytest.fixture
def mock_evnex(mock_evnex_client):
    """Patch the Evnex class used by the config flow."""
    with patch(
        "custom_components.evnex.config_flow.Evnex",
        return_value=mock_evnex_client,
    ):
        yield mock_evnex_client


def mfa_challenge():
    return SoftwareTokenMFAChallengeException(
        "Do Software Token MFA",
        {"ChallengeName": "SOFTWARE_TOKEN_MFA", "Session": "opaque-session"},
    )
