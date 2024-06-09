"""
Custom integration to integrate ChargePoint with Home Assistant.

"""
import os
import json
import logging
from datetime import timedelta
from typing import Optional

from evnex.api import Evnex
from evnex.schema.charge_points import EvnexChargePoint, EvnexChargePointOverrideConfig
from evnex.schema.v3.charge_points import EvnexChargePointDetail

from evnex.schema.user import EvnexUserDetail
from evnex.errors import NotAuthorizedException

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from httpx import HTTPStatusError

from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    ISSUE_URL,
    PLATFORMS,
    VERSION,
    TOKEN_FILE_NAME,
)

SCAN_INTERVAL = timedelta(minutes=5)

_LOGGER: logging.Logger = logging.getLogger(__package__)


def persist_evnex_auth_tokens(
    hass: HomeAssistant,
    entry: ConfigEntry,
    id_token=None,
    refresh_token=None,
    access_token=None,
) -> None:
    config_dir = hass.config.config_dir
    file = os.path.join(config_dir, TOKEN_FILE_NAME)
    session_dict = {}
    if os.path.isfile(file):
        with open(file, "r") as spf:
            try:
                session_dict = json.load(spf)
            except json.decoder.JSONDecodeError:
                _LOGGER.error("Failed to load existing session data, overwriting!")
    _LOGGER.info("Persisting session tokens to %s", file)
    session_dict[entry.entry_id] = {
        "id_token": id_token,
        "refresh_token": refresh_token,
        "access_token": access_token,
    }

    with open(os.open(file, os.O_CREAT | os.O_WRONLY, 0o600), "w") as spf:
        json.dump(session_dict, spf)


def retrieve_evnex_auth_tokens(
    hass: HomeAssistant, entry: ConfigEntry
) -> Optional[dict]:
    config_dir = hass.config.config_dir
    file = os.path.join(config_dir, TOKEN_FILE_NAME)
    _LOGGER.info("Retrieving session token from: %s", file)
    if os.path.isfile(file):
        with open(file, "r") as spf:
            try:
                sessions = json.load(spf)
                return sessions.get(entry.entry_id)
            except json.decoder.JSONDecodeError:
                _LOGGER.error("Failed to decode JSON session data in %s", file)
                return None


async def async_setup(hass: HomeAssistant, entry: ConfigEntry):
    """Disallow configuration via YAML"""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Load the saved entities."""
    _LOGGER.info(
        "Version %s is starting, if you have any issues please report" " them here: %s",
        VERSION,
        ISSUE_URL,
    )

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    # Load tokens from storage
    evnex_auth_tokens = retrieve_evnex_auth_tokens(hass, entry)
    evnex_auth_tokens = {} if evnex_auth_tokens is None else evnex_auth_tokens

    httpx_client = get_async_client(hass)

    try:
        evnex_client: Evnex = await hass.async_add_executor_job(
            Evnex,
            username,
            password,
            evnex_auth_tokens.get("id_token"),
            evnex_auth_tokens.get("refresh_token"),
            evnex_auth_tokens.get("access_token"),
            None,
            httpx_client,
        )

    except NotAuthorizedException as exc:
        _LOGGER.error("Not authorized while updating evnex info")
        raise ConfigEntryAuthFailed from exc
    except HTTPStatusError as exc:
        _LOGGER.error("Failed to authenticate to evnex api")
        raise ConfigEntryAuthFailed from exc

    hass.data.setdefault(DOMAIN, {})

    async def async_update_data(is_retry: bool = False):
        """Fetch data from EVNEX API"""

        data = {
            "user": None,
            "org_briefs": {},  # by org_id
            "org_insights": {},  # by org_id
            "charge_points": {},  # by_org_id
            "charge_point_brief": {},  # by cp_id
            "charge_point_details": {},  # by cp_id
            "charge_point_override": {},  # by cp_id
            "charge_point_sessions": {},  # by cp_id
            "connector_brief": {},  # by (cp_id, connectorId)
        }

        try:
            _LOGGER.info("Getting evnex user detail")

            account: EvnexUserDetail = await evnex_client.get_user_detail()

            persist_evnex_auth_tokens(
                hass,
                entry,
                evnex_client.id_token,
                evnex_client.refresh_token,
                evnex_client.access_token,
            )

            data["user"] = account

            for org in account.organisations:
                _LOGGER.info(f"Getting evnex charge points for '{org.name}'")
                charge_points: list[
                    EvnexChargePoint
                ] = await evnex_client.get_org_charge_points(org.slug)
                data["charge_points"][org.id] = [cp for cp in charge_points]
                data["org_briefs"][org.id] = org
                _LOGGER.debug(f"Getting evnex org insights for {org.name}")
                daily_insights = await evnex_client.get_org_insight(
                    days=7, org_id=org.slug
                )
                data["org_insights"][org.id] = daily_insights

                for charge_point in charge_points:
                    _LOGGER.debug(
                        f"Getting evnex charge point data for '{charge_point.name}'"
                    )
                    # Migrated to v3 charge point detail which includes more info
                    api_v3_response = await evnex_client.get_charge_point_detail_v3(
                        charge_point_id=charge_point.id
                    )
                    charge_point_detail: EvnexChargePointDetail = (
                        api_v3_response.data.attributes
                    )

                    for connector_brief in charge_point_detail["connectors"]:
                        data["connector_brief"][
                            (charge_point.id, connector_brief["connectorId"])
                        ] = connector_brief

                    _LOGGER.debug(
                        f"Getting evnex charge point sessions for '{charge_point.name}'"
                    )
                    charge_point_sessions = (
                        await evnex_client.get_charge_point_sessions(
                            charge_point_id=charge_point.id
                        )
                    )

                    # Only get the charge point override if the charge point is online!
                    if charge_point_detail["networkStatus"] == "ONLINE":
                        _LOGGER.debug(
                            f"Getting evnex charge point override for '{charge_point.name}'"
                        )
                        charge_point_override: EvnexChargePointOverrideConfig = (
                            await evnex_client.get_charge_point_override(
                                charge_point_id=charge_point.id
                            )
                        )
                    else:
                        _LOGGER.debug(
                            "Not getting charge point override as charge point is not ONLINE"
                        )
                        charge_point_override = None

                    data["charge_point_brief"][charge_point.id] = charge_point
                    data["charge_point_details"][charge_point.id] = charge_point_detail
                    data["charge_point_override"][
                        charge_point.id
                    ] = charge_point_override
                    data["charge_point_sessions"][
                        charge_point.id
                    ] = charge_point_sessions

            return data
        except NotAuthorizedException:
            if not is_retry:
                _LOGGER.debug("Refreshing auth and trying again")
                await hass.async_add_executor_job(evnex_client.authenticate)
                persist_evnex_auth_tokens(
                    hass,
                    entry,
                    evnex_client.id_token,
                    evnex_client.refresh_token,
                    evnex_client.access_token,
                )
                return await async_update_data(is_retry=True)
            _LOGGER.warning(
                "EVNEX Session Token is invalid and failed attempt to re-login"
            )
            raise
        except Exception as err:
            _LOGGER.exception("Unhandled exception while updating evnex info")
            raise UpdateFailed from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(minutes=3),
    )

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: evnex_client,
        DATA_COORDINATOR: coordinator,
    }

    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later

    await coordinator.async_config_entry_first_refresh()

    # Setup components
    # hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
