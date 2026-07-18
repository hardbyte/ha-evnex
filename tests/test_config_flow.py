"""Tests for the evnex config flow, including MFA and reauthentication."""

from evnex.errors import (
    ChallengeExpiredError,
    InvalidChallengeResponseError,
    InvalidCredentialsError,
    PasswordChangeRequiredError,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.evnex.const import DOMAIN

from .conftest import USER_ID, make_token_set, mfa_challenge

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
    assert result["data"]["tokens"] == make_token_set().to_dict()
    assert result["data"]["user_id"] == USER_ID
    assert "password" not in result["data"]
    mock_evnex.auth.start_authentication.assert_called_once_with(
        CREDS["username"], CREDS["password"]
    )


async def test_user_flow_with_mfa(hass: HomeAssistant, mock_evnex) -> None:
    challenge = mfa_challenge()
    mock_evnex.auth.start_authentication.return_value = challenge

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mfa"
    assert result["description_placeholders"] == {
        "mfa_source": "your authenticator app"
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mfa_code": "123456"}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test User"
    mock_evnex.auth.respond_to_challenge.assert_called_once_with(challenge, "123456")


async def test_mfa_wrong_code_shows_error_and_recovers(
    hass: HomeAssistant, mock_evnex
) -> None:
    challenge = mfa_challenge()
    mock_evnex.auth.start_authentication.return_value = challenge
    mock_evnex.auth.respond_to_challenge.side_effect = [
        InvalidChallengeResponseError("Wrong code"),
        make_token_set(),
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
    # Both attempts answered the same challenge.
    for call in mock_evnex.auth.respond_to_challenge.call_args_list:
        assert call.args[0] is challenge


async def test_mfa_expired_then_restarts(hass: HomeAssistant, mock_evnex) -> None:
    first_challenge = mfa_challenge()
    second_challenge = mfa_challenge()
    mock_evnex.auth.start_authentication.side_effect = [
        first_challenge,
        second_challenge,
    ]
    mock_evnex.auth.respond_to_challenge.side_effect = [
        ChallengeExpiredError("Session lapsed"),
        make_token_set(),
    ]

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mfa_code": "000000"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mfa"
    assert result["errors"] == {"base": "mfa_expired"}
    assert mock_evnex.auth.start_authentication.call_count == 2

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mfa_code": "123456"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    # The second attempt answered the freshly issued challenge.
    assert mock_evnex.auth.respond_to_challenge.call_args_list[1].args[0] == (
        second_challenge
    )


async def test_mfa_expired_restart_unexpected_error_shows_unknown(
    hass: HomeAssistant, mock_evnex
) -> None:
    """An unexpected error while restarting after expiry surfaces as "unknown"."""
    from evnex.errors import EvnexAuthError

    challenge = mfa_challenge()
    mock_evnex.auth.start_authentication.side_effect = [
        challenge,
        EvnexAuthError("session verification failed"),
    ]
    mock_evnex.auth.respond_to_challenge.side_effect = ChallengeExpiredError(
        "Session lapsed"
    )

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"mfa_code": "000000"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "mfa"
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_invalid_credentials(hass: HomeAssistant, mock_evnex) -> None:
    mock_evnex.auth.start_authentication.side_effect = InvalidCredentialsError(
        "Bad creds"
    )

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_credentials"}


async def test_user_flow_password_change_required_aborts(
    hass: HomeAssistant, mock_evnex
) -> None:
    mock_evnex.auth.start_authentication.side_effect = PasswordChangeRequiredError(
        "Password change required"
    )

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "password_change_required"


async def test_duplicate_account_aborts(hass: HomeAssistant, mock_evnex) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_ID,
        data={"username": CREDS["username"], "tokens": make_token_set().to_dict()},
        minor_version=4,
    ).add_to_hass(hass)

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_with_mfa(hass: HomeAssistant, mock_evnex) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_ID,
        minor_version=4,
        data={
            "username": CREDS["username"],
            "user_id": USER_ID,
            "tokens": make_token_set(access_token=None).to_dict(),
        },
    )
    entry.add_to_hass(hass)
    challenge = mfa_challenge()
    mock_evnex.auth.start_authentication.return_value = challenge

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
    assert entry.data["tokens"] == make_token_set().to_dict()
    assert "password" not in entry.data
    assert "id_token" not in entry.data
    assert "refresh_token" not in entry.data
    assert "access_token" not in entry.data


async def test_reauth_legacy_entry_without_user_id_blocks_wrong_account(
    hass: HomeAssistant, mock_evnex
) -> None:
    """A legacy entry lacking user_id still blocks a different account.

    The account-identity check must key off the entry's unique_id (set at
    creation) rather than a stored user_id field that pre-user_id entries
    migrated up to the current version may not have.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="different-user",
        minor_version=4,
        # No user_id in data, as for an entry created before it was recorded.
        data={"username": CREDS["username"], "tokens": make_token_set().to_dict()},
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


async def test_reauth_wrong_account_aborts(hass: HomeAssistant, mock_evnex) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="different-user",
        minor_version=4,
        data={
            "username": CREDS["username"],
            "user_id": "different-user",
            "tokens": make_token_set().to_dict(),
        },
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
