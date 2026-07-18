"""Shared fixtures for evnex integration tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from evnex.auth import AuthChallenge, TokenSet

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


def make_token_set(access_token="access-0"):
    return TokenSet(
        access_token=access_token, id_token="id-0", refresh_token="refresh-0"
    )


@pytest.fixture
def mock_auth():
    """A mocked EvnexAuth that authenticates without a challenge."""
    auth = MagicMock()
    auth.start_authentication = AsyncMock(return_value=make_token_set())
    auth.respond_to_challenge = AsyncMock(return_value=make_token_set())
    auth.tokens = make_token_set()
    return auth


@pytest.fixture
def mock_evnex_client():
    """A mocked Evnex client returned once auth succeeds."""
    client = MagicMock()
    client.get_user_detail = AsyncMock(return_value=make_user_detail())
    client.org_id = "org-1"
    return client


@pytest.fixture
def mock_evnex(mock_auth, mock_evnex_client):
    """Patch EvnexAuth and Evnex as used by the config flow.

    The returned mock is the Evnex client, with the EvnexAuth mock attached
    as `.auth` for tests that need to drive authentication behaviour (e.g.
    setting `side_effect` on `start_authentication`/`respond_to_challenge`).
    """
    mock_evnex_client.auth = mock_auth
    with (
        patch(
            "custom_components.evnex.config_flow.EvnexAuth",
            return_value=mock_auth,
        ),
        patch(
            "custom_components.evnex.config_flow.Evnex",
            return_value=mock_evnex_client,
        ),
    ):
        yield mock_evnex_client


def mfa_challenge(friendly_device_name: str | None = "your authenticator app"):
    parameters = {}
    if friendly_device_name is not None:
        parameters["FRIENDLY_DEVICE_NAME"] = friendly_device_name
    return AuthChallenge(
        name="SOFTWARE_TOKEN_MFA",
        session="opaque-session",
        username="user@example.com",
        parameters=parameters,
    )
