"""Tests for the evnex integration setup, migration, and coordinator."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from evnex.auth import TokenSet
from evnex.errors import ReauthenticationRequiredError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from httpx import HTTPStatusError, ReadTimeout, Request, Response
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


def _online_charger_client(override_side_effect) -> MagicMock:
    """A client with one org and one ONLINE charge point; the override call is driven by the test."""
    org = MagicMock()
    org.id, org.name, org.slug = "org-1", "Home", "home"
    user = MagicMock()
    user.organisations = [org]
    charge_point = MagicMock()
    charge_point.id, charge_point.name = "cp-1", "Garage"
    detail = MagicMock()
    detail.data.attributes.networkStatus = "ONLINE"
    detail.data.attributes.connectors = []

    client = MagicMock()
    client.get_user_detail = AsyncMock(return_value=user)
    client.get_org_charge_points = AsyncMock(return_value=[charge_point])
    client.get_org_insight = AsyncMock(return_value=[])
    client.get_charge_point_detail_v3 = AsyncMock(return_value=detail)
    client.get_charge_point_sessions = AsyncMock(return_value=[])
    client.get_charge_point_override = AsyncMock(side_effect=override_side_effect)
    return client


def _rate_limited() -> HTTPStatusError:
    request = Request(
        "POST", "https://client-api.evnex.io/charge-points/cp-1/commands/get-override"
    )
    return HTTPStatusError(
        "Client error '429 Too Many Requests'",
        request=request,
        response=Response(429, request=request),
    )


@pytest.mark.parametrize(
    "error",
    [_rate_limited(), ReadTimeout("timed out")],
    ids=["429", "read-timeout"],
)
async def test_coordinator_keeps_last_override_when_override_read_fails(
    hass: HomeAssistant, error: Exception
) -> None:
    """A failed override read neither fails the update nor drops the last known override (#115)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_ID,
        data={"username": "user@example.com", "tokens": make_token_set().to_dict()},
    )
    entry.add_to_hass(hass)
    previous = MagicMock(chargeNow=True)
    client = _online_charger_client([previous, error])
    coordinator = EvnexCoordinator(hass, client, entry)

    coordinator.data = await coordinator._async_update_data()
    data = await coordinator._async_update_data()

    assert data.charge_point_override["cp-1"] is previous
    assert "cp-1" in data.charge_point_details  # the rest of the update survived


async def test_coordinator_continues_without_override_on_first_failure(
    hass: HomeAssistant,
) -> None:
    """With no previous value, a 429 on the override read still lets the update succeed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_ID,
        data={"username": "user@example.com", "tokens": make_token_set().to_dict()},
    )
    entry.add_to_hass(hass)
    coordinator = EvnexCoordinator(hass, _online_charger_client(_rate_limited()), entry)

    data = await coordinator._async_update_data()

    assert "cp-1" not in data.charge_point_override
    assert "cp-1" in data.charge_point_details
