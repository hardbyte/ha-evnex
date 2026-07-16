"""Config flow for Evnex EV Charger integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import AbortFlow, FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.httpx_client import get_async_client

from evnex.api import Evnex
from evnex.errors import NotAuthorizedException
from pycognito.exceptions import (
    SMSMFAChallengeException,
    SoftwareTokenMFAChallengeException,
)

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ID_TOKEN,
    CONF_MFA_CODE,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

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
    MINOR_VERSION = 3

    def __init__(self) -> None:
        self._client: Evnex | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._mfa_mode: str | None = None
        self._reauth_entry: ConfigEntry | None = None

    async def _async_start_auth(self) -> str | None:
        """Authenticate with username/password.

        Returns the MFA mode ("TOTP" or "SMS") when the account requires a
        code to finish signing in, or None when fully authenticated.

        :raises InvalidAuth
        """

        def _create_client() -> Evnex:
            # boto3 client construction inside Evnex/Cognito can perform
            # blocking I/O (credential lookup), so keep it off the event loop
            return Evnex(
                username=self._username,
                password=self._password,
                httpx_client=get_async_client(self.hass),
            )

        self._client = await self.hass.async_add_executor_job(_create_client)
        try:
            await self.hass.async_add_executor_job(self._client.authenticate)
        except SoftwareTokenMFAChallengeException:
            return "TOTP"
        except SMSMFAChallengeException:
            return "SMS"
        except NotAuthorizedException as err:
            raise InvalidAuth from err
        return None

    def _show_mfa_form(self, errors: dict[str, str] | None = None) -> FlowResult:
        return self.async_show_form(
            step_id="mfa",
            data_schema=STEP_MFA_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "mfa_source": "your authenticator app"
                if self._mfa_mode == "TOTP"
                else "the SMS we sent you"
            },
        )

    async def _async_create_or_update_entry(self) -> FlowResult:
        """Fetch account details and create (or update, on reauth) the entry."""
        user_data = await self._client.get_user_detail()

        data = {
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            "user_id": str(user_data.id),
            "default_org_id": self._client.org_id,
            CONF_ID_TOKEN: self._client.id_token,
            CONF_REFRESH_TOKEN: self._client.refresh_token,
            CONF_ACCESS_TOKEN: self._client.access_token,
        }

        if self._reauth_entry is not None:
            stored_user_id = self._reauth_entry.data.get("user_id")
            if stored_user_id is not None and stored_user_id != str(user_data.id):
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._reauth_entry, data={**self._reauth_entry.data, **data}
            )

        await self.async_set_unique_id(str(user_data.id))
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=user_data.name or user_data.email, data=data
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        self._username = user_input[CONF_USERNAME].lower()
        self._password = user_input[CONF_PASSWORD]

        errors = {}
        try:
            if mfa_mode := await self._async_start_auth():
                self._mfa_mode = mfa_mode
                return self._show_mfa_form()
            return await self._async_create_or_update_entry()
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_credentials"
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
    ) -> FlowResult:
        """Verify a multifactor authentication code."""
        errors = {}

        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    self._client.respond_to_mfa_challenge,
                    user_input[CONF_MFA_CODE].strip(),
                    self._mfa_mode,
                )
                return await self._async_create_or_update_entry()
            except NotAuthorizedException:
                # Wrong code, or the short-lived Cognito challenge session
                # expired; restart the challenge so the next attempt can work.
                errors["base"] = "invalid_mfa_code"
                try:
                    await self._async_start_auth()
                except InvalidAuth:
                    errors["base"] = "invalid_credentials"
            except AbortFlow:
                raise
            except Exception:  # pylint: disable=broad-except
                logger.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self._show_mfa_form(errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle reauthentication when stored tokens are no longer valid."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._username = entry_data[CONF_USERNAME]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm the password (and MFA, if enabled) to re-establish a session."""
        errors = {}

        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            try:
                if mfa_mode := await self._async_start_auth():
                    self._mfa_mode = mfa_mode
                    return self._show_mfa_form()
                return await self._async_create_or_update_entry()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_credentials"
            except AbortFlow:
                raise
            except Exception:  # pylint: disable=broad-except
                logger.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"username": self._username},
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
