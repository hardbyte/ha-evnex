"""
Custom integration to integrate Evnex with Home Assistant.

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
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, Platform
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from httpx import HTTPStatusError, ReadTimeout

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

    return None


async def async_setup(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Disallow configuration via YAML"""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load the saved entities."""
    _LOGGER.info(
        "Version %s is starting, if you have any issues please report them here: %s",
        VERSION,
        ISSUE_URL,
    )

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    # Load tokens from storage
    evnex_auth_tokens = await hass.async_add_executor_job(
        retrieve_evnex_auth_tokens, hass, entry
    )
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

    await _async_migrate_entries(hass, entry)

    async def async_update_data(is_retry: bool = False):
        """Fetch data from EVNEX API"""

        data: dict = {
            "user": None,
            "org_briefs": {},  # by org_id
            "org_insights": {},  # by org_id
            "charge_points_by_org": {},  # by_org_id -> list of CPs
            "charge_point_brief": {},  # by cp_id
            "charge_point_details": {},  # by cp_id
            "charge_point_override": {},  # by cp_id
            "charge_point_sessions": {},  # by cp_id
            "connector_brief": {},  # by (cp_id, connectorId)
            "charge_point_to_org_map": {},  # by cp_id -> org_id
        }

        try:
            _LOGGER.info("Getting evnex user detail")
            account: EvnexUserDetail = await evnex_client.get_user_detail()

            await hass.async_add_executor_job(
                persist_evnex_auth_tokens,
                hass,
                entry,
                evnex_client.id_token,
                evnex_client.refresh_token,
                evnex_client.access_token,
            )

            data["user"] = account

            for org in account.organisations:
                _LOGGER.info(
                    f"Getting evnex charge points for '{org.name}' (Org ID: {org.id}, Slug: {org.slug})"
                )
                charge_points: list[EvnexChargePoint] = list()
                try:
                    charge_points = await evnex_client.get_org_charge_points(org.id)
                except HTTPStatusError:
                    _LOGGER.info("Org ID not supported switching to Slug")
                    charge_points = await evnex_client.get_org_charge_points(org.slug)
                data["charge_points_by_org"][org.id] = [cp for cp in charge_points]
                data["org_briefs"][org.id] = org
                _LOGGER.debug(f"Getting evnex org insights for {org.name}")
                daily_insights = await evnex_client.get_org_insight(
                    days=7, org_id=org.id
                )
                data["org_insights"][org.id] = daily_insights

                for charge_point in charge_points:
                    data["charge_point_to_org_map"][charge_point.id] = (
                        org.id
                    )  # Map charge_point.id back to org.id

                    _LOGGER.debug(
                        f"Getting evnex charge point data for '{charge_point.name}'"
                    )
                    api_v3_response = await evnex_client.get_charge_point_detail_v3(
                        charge_point_id=charge_point.id
                    )
                    charge_point_detail: EvnexChargePointDetail = (
                        api_v3_response.data.attributes
                    )

                    for connector_brief in charge_point_detail.connectors:
                        data["connector_brief"][
                            (charge_point.id, connector_brief.connectorId)
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
                    if charge_point_detail.networkStatus == "ONLINE":
                        _LOGGER.debug(
                            f"Getting evnex charge point override for '{charge_point.name}'"
                        )
                        # Don't block data update if a read timeout encountered
                        try:
                            charge_point_override: EvnexChargePointOverrideConfig = (
                                await evnex_client.get_charge_point_override(
                                    charge_point_id=charge_point.id
                                )
                            )
                        except ReadTimeout:
                            _LOGGER.warning(
                                "Read timeout prevented getting charge point override"
                            )
                            charge_point_override = None
                    else:
                        _LOGGER.debug(
                            "Not getting charge point override as charge point is not ONLINE"
                        )
                        charge_point_override = None

                    data["charge_point_brief"][charge_point.id] = charge_point
                    data["charge_point_details"][charge_point.id] = charge_point_detail
                    data["charge_point_override"][charge_point.id] = (
                        charge_point_override
                    )
                    data["charge_point_sessions"][charge_point.id] = (
                        charge_point_sessions
                    )

            # Keep old key for migration purposes - can remove in future versions
            data["charge_points"] = data["charge_points_by_org"]
            return data
        except NotAuthorizedException:
            if not is_retry:
                _LOGGER.debug("Refreshing auth and trying again")
                await hass.async_add_executor_job(evnex_client.authenticate)
                await hass.async_add_executor_job(
                    persist_evnex_auth_tokens,
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
            _LOGGER.exception(
                f"Unhandled exception while updating evnex info {err=} {type(err)}"
            )
            raise UpdateFailed from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
        config_entry=entry,
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


async def _async_migrate_entries(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Migrate old entry."""
    entity_registry = er.async_get(hass)

    @callback
    def update_unique_id(entry: er.RegistryEntry) -> dict[str, str] | None:
        replacements = {
            Platform.SENSOR.value: {
                "org_wide_power_usage_today": "_org_wide_power_usage_today",
                "org_wide_charger_sessions_today": "_org_wide_charger_sessions_today",
                "org_tier": "_org_tier",
                "charger_network_status": "_charger_network_status",
                "session_energy": "_session_energy",
                "session_cost": "_session_cost",
                "session_time": "_session_time",
                "session_start_time": "_session_start_time",
                "charger_session_history": "_charger_session_history",
                "_1_connector_current": "_1_connector_current_l1",
                "_1_connector_voltage": "_1_connector_voltage_l1",
            },
            Platform.SWITCH.value: {
                "charger_charge_now_switch": "_charger_charge_now",
                "_1_connector_1_availability_switch": "_1_connector_1_availability",
            },
            Platform.BUTTON.value: {
                "charger_stop_session": "_charger_stop_session",
            },
        }
        uuid_part = entry.unique_id[:36]  # UUID is always 36 chars with dashes
        remainder = entry.unique_id[36:]
        if (key := remainder) in replacements.get(entry.domain, []):
            new_unique_id = entry.unique_id.replace(
                f"{uuid_part}{key}", f"{uuid_part}{replacements[entry.domain][key]}"
            )
            _LOGGER.debug(
                "Migrating entity '%s' unique_id from '%s' to '%s'",
                entry.entity_id,
                entry.unique_id,
                new_unique_id,
            )
            if existing_entity_id := entity_registry.async_get_entity_id(
                entry.domain, entry.platform, new_unique_id
            ):
                _LOGGER.debug(
                    "Cannot migrate to unique_id '%s', already exists for '%s'",
                    new_unique_id,
                    existing_entity_id,
                )
                return None
            return {
                "new_unique_id": new_unique_id,
            }
        return None

    if config_entry.version == 1 and config_entry.minor_version < 2:
        await er.async_migrate_entries(hass, config_entry.entry_id, update_unique_id)
        config_entry.minor_version = 2

    return True
