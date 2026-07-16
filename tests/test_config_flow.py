"""Tests for the evnex config flow, including MFA and reauthentication."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.evnex.const import DOMAIN

from .conftest import USER_ID, mfa_challenge

CREDS = {"username": "user@example.com", "password": "hunter2"}


async def start_user_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_user_flow_without_mfa(hass: HomeAssistant, mock_evnex) -> None:
    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test User"
    assert result["data"]["access_token"] == "access-0"
    assert result["data"]["refresh_token"] == "refresh-0"
    assert result["data"]["user_id"] == USER_ID
    mock_evnex.authenticate.assert_called_once()


async def test_user_flow_with_mfa(hass: HomeAssistant, mock_evnex) -> None:
    mock_evnex.authenticate.side_effect = mfa_challenge()

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mfa"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mfa_code": "123456"}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test User"
    mock_evnex.respond_to_mfa_challenge.assert_called_once_with("123456", "TOTP")


async def test_mfa_wrong_code_shows_error_and_recovers(
    hass: HomeAssistant, mock_evnex
) -> None:
    from evnex.errors import NotAuthorizedException

    mock_evnex.authenticate.side_effect = mfa_challenge()
    mock_evnex.respond_to_mfa_challenge.side_effect = [
        NotAuthorizedException("Wrong code"),
        None,
    ]

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mfa_code": "000000"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mfa"
    assert result["errors"] == {"base": "invalid_mfa_code"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mfa_code": "123456"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_user_flow_invalid_credentials(hass: HomeAssistant, mock_evnex) -> None:
    from evnex.errors import NotAuthorizedException

    mock_evnex.authenticate.side_effect = NotAuthorizedException("Bad creds")

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_credentials"}


async def test_duplicate_account_aborts(hass: HomeAssistant, mock_evnex) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id=USER_ID, data=CREDS, minor_version=3
    ).add_to_hass(hass)

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_with_mfa(hass: HomeAssistant, mock_evnex) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_ID,
        minor_version=3,
        data={**CREDS, "user_id": USER_ID, "access_token": None},
    )
    entry.add_to_hass(hass)
    mock_evnex.authenticate.side_effect = mfa_challenge()

    entry.async_start_reauth(hass)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"password": "hunter2"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mfa"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mfa_code": "123456"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["access_token"] == "access-0"


async def test_reauth_wrong_account_aborts(hass: HomeAssistant, mock_evnex) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="different-user",
        minor_version=3,
        data={**CREDS, "user_id": "different-user"},
    )
    entry.add_to_hass(hass)

    entry.async_start_reauth(hass)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"password": "hunter2"}
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
