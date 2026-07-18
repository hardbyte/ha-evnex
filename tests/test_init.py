"""Tests for the evnex integration setup, migration, and coordinator."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from evnex.auth import TokenSet
from evnex.errors import ReauthenticationRequiredError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.evnex import async_migrate_entry
from custom_components.evnex.const import DOMAIN
from custom_components.evnex.coordinator import EvnexCoordinator, EvnexRuntimeData

from .conftest import USER_ID, make_token_set


async def test_migrate_1_3_to_1_4_folds_tokens_and_drops_password(
    hass: HomeAssistant,
) -> None:
    """Flat token fields collapse into a single "tokens" entry, no password."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_ID,
        version=1,
        minor_version=3,
        data={
            "username": "user@example.com",
            "password": "hunter2",
            "user_id": USER_ID,
            "default_org_id": "org-1",
            "id_token": "id-0",
            "refresh_token": "refresh-0",
            "access_token": "access-0",
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.minor_version == 4
    assert (
        entry.data["tokens"]
        == TokenSet(
            id_token="id-0", refresh_token="refresh-0", access_token="access-0"
        ).to_dict()
    )
    assert "password" not in entry.data
    assert "id_token" not in entry.data
    assert "refresh_token" not in entry.data
    assert "access_token" not in entry.data
    # Untouched fields survive the migration.
    assert entry.data["username"] == "user@example.com"
    assert entry.data["user_id"] == USER_ID
    assert entry.data["default_org_id"] == "org-1"


async def test_migrate_full_chain_from_1_1(hass: HomeAssistant) -> None:
    """A version 1.1 entry migrates all the way to 1.4 in a single pass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_ID,
        version=1,
        minor_version=1,
        data={
            "username": "user@example.com",
            "password": "hunter2",
            "user_id": USER_ID,
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.minor_version == 4
    # No token file exists in the test config dir, so tokens fold to all-None.
    assert entry.data["tokens"] == TokenSet().to_dict()
    assert "password" not in entry.data
    assert "id_token" not in entry.data
    assert "refresh_token" not in entry.data
    assert "access_token" not in entry.data
    assert entry.data["username"] == "user@example.com"


async def test_coordinator_reauth_required_raises_config_entry_auth_failed(
    hass: HomeAssistant,
) -> None:
    """A ReauthenticationRequiredError from the client triggers reauth."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_ID,
        data={"username": "user@example.com", "tokens": make_token_set().to_dict()},
    )
    entry.add_to_hass(hass)

    client = MagicMock()
    client.get_user_detail = AsyncMock(
        side_effect=ReauthenticationRequiredError("Session expired")
    )

    coordinator = EvnexCoordinator(hass, client, entry)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_runtime_data_wiring(hass: HomeAssistant) -> None:
    """EvnexRuntimeData exposes the client and coordinator set on the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_ID,
        data={"username": "user@example.com", "tokens": make_token_set().to_dict()},
    )
    entry.add_to_hass(hass)

    client = MagicMock()
    coordinator = EvnexCoordinator(hass, client, entry)
    entry.runtime_data = EvnexRuntimeData(client=client, coordinator=coordinator)

    assert entry.runtime_data.client is client
    assert entry.runtime_data.coordinator is coordinator
