"""Config flow for Evnex EV Charger integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.httpx_client import get_async_client

from evnex.api import Evnex
from evnex.auth import AuthChallenge, EvnexAuth, TokenSet
from evnex.errors import (
    ChallengeExpiredError,
    InvalidChallengeResponseError,
    InvalidCredentialsError,
    PasswordChangeRequiredError,
)

from .const import CONF_MFA_CODE, DOMAIN

logger = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_MFA_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MFA_CODE): str,
    }
)


class EvnexConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore
    """Handle a config flow for Evnex EV Charger."""

    VERSION = 1
    MINOR_VERSION = 4

    def __init__(self) -> None:
        self._auth: EvnexAuth | None = None
        self._challenge: AuthChallenge | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._reauth_entry: ConfigEntry | None = None

    def _show_mfa_form(self, errors: dict[str, str] | None = None) -> ConfigFlowResult:
        assert self._challenge is not None
        mfa_source = (
            self._challenge.parameters.get("FRIENDLY_DEVICE_NAME")
            or "your authenticator app"
        )
        return self.async_show_form(
            step_id="mfa",
            data_schema=STEP_MFA_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"mfa_source": mfa_source},
        )

    async def _async_finalize(self) -> ConfigFlowResult:
        """Fetch account details and create (or update, on reauth) the entry."""
        assert self._auth is not None and self._auth.tokens is not None

        client = Evnex(auth=self._auth, httpx_client=get_async_client(self.hass))
        user = await client.get_user_detail()

        data = {
            CONF_USERNAME: self._username,
            "user_id": str(user.id),
            "default_org_id": client.org_id,
            "tokens": self._auth.tokens.to_dict(),
        }

        if self._reauth_entry is not None:
            stored_user_id = self._reauth_entry.data.get("user_id")
            if stored_user_id is not None and stored_user_id != str(user.id):
                return self.async_abort(reason="wrong_account")
            merged_data = {**self._reauth_entry.data, **data}
            merged_data.pop(CONF_PASSWORD, None)
            merged_data.pop("id_token", None)
            merged_data.pop("refresh_token", None)
            merged_data.pop("access_token", None)
            return self.async_update_reload_and_abort(
                self._reauth_entry, data=merged_data
            )

        await self.async_set_unique_id(str(user.id))
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title=user.name or user.email, data=data)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        self._username = user_input[CONF_USERNAME].lower()
        self._password = user_input[CONF_PASSWORD]

        errors: dict[str, str] = {}
        try:
            self._auth = EvnexAuth()
            result = await self._auth.start_authentication(
                self._username, self._password
            )
            if isinstance(result, AuthChallenge):
                self._challenge = result
                return self._show_mfa_form()
            return await self._async_finalize()
        except InvalidCredentialsError:
            errors["base"] = "invalid_credentials"
        except PasswordChangeRequiredError:
            return self.async_abort(reason="password_change_required")
        except AbortFlow:
            raise
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unexpected exception")
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify a multifactor authentication code."""
        errors: dict[str, str] = {}

        if user_input is not None:
            assert self._auth is not None and self._challenge is not None
            try:
                result = await self._auth.respond_to_challenge(
                    self._challenge, user_input[CONF_MFA_CODE].strip()
                )
                if isinstance(result, TokenSet):
                    return await self._async_finalize()
                self._challenge = result
                return self._show_mfa_form()
            except InvalidChallengeResponseError:
                errors["base"] = "invalid_mfa_code"
            except ChallengeExpiredError:
                try:
                    result = await self._auth.start_authentication(
                        self._username, self._password
                    )
                except InvalidCredentialsError:
                    errors["base"] = "invalid_credentials"
                    return self.async_show_form(
                        step_id="user",
                        data_schema=STEP_USER_DATA_SCHEMA,
                        errors=errors,
                    )
                except PasswordChangeRequiredError:
                    return self.async_abort(reason="password_change_required")
                except Exception:  # pylint: disable=broad-except
                    logger.exception("Unexpected exception restarting authentication")
                    return self._show_mfa_form({"base": "unknown"})
                if isinstance(result, TokenSet):
                    return await self._async_finalize()
                self._challenge = result
                errors["base"] = "mfa_expired"
            except PasswordChangeRequiredError:
                return self.async_abort(reason="password_change_required")
            except AbortFlow:
                raise
            except Exception:  # pylint: disable=broad-except
                logger.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self._show_mfa_form(errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauthentication when stored tokens are no longer valid."""
        self._reauth_entry = self._get_reauth_entry()
        self._username = entry_data[CONF_USERNAME]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the password (and MFA, if enabled) to re-establish a session."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            try:
                self._auth = EvnexAuth()
                result = await self._auth.start_authentication(
                    self._username, self._password
                )
                if isinstance(result, AuthChallenge):
                    self._challenge = result
                    return self._show_mfa_form()
                return await self._async_finalize()
            except InvalidCredentialsError:
                errors["base"] = "invalid_credentials"
            except PasswordChangeRequiredError:
                return self.async_abort(reason="password_change_required")
            except AbortFlow:
                raise
            except Exception:  # pylint: disable=broad-except
                logger.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"username": self._username or ""},
        )
