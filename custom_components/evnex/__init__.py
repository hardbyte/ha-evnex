"""
Custom integration to integrate Evnex with Home Assistant.

"""

import json
import logging
import os
from datetime import timedelta

from evnex.api import Evnex
from evnex.schema.charge_points import EvnexChargePoint, EvnexChargePointOverrideConfig
from evnex.schema.v3.charge_points import EvnexChargePointDetail

from evnex.schema.user import EvnexUserDetail
from evnex.errors import NotAuthorizedException
from pycognito.exceptions import MFAChallengeException

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
    CONF_ACCESS_TOKEN,
    CONF_ID_TOKEN,
    CONF_REFRESH_TOKEN,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    ISSUE_URL,
    PLATFORMS,
    TOKEN_FILE_NAME,
    VERSION,
)
from .models import EvnexCoordinatorData

SCAN_INTERVAL = timedelta(minutes=5)

_LOGGER: logging.Logger = logging.getLogger(__package__)


def _read_tokens_from_file(hass: HomeAssistant, entry: ConfigEntry) -> dict | None:
    """Read auth tokens from the legacy file-based storage. Used only for migration."""
    config_dir = hass.config.config_dir
    file = os.path.join(config_dir, TOKEN_FILE_NAME)
    _LOGGER.debug("Reading legacy session tokens from: %s", file)
    if os.path.isfile(file):
        with open(file, "r") as spf:
            content = spf.read()
        try:
            # Tolerate stale trailing bytes after the JSON object (issue #87)
            sessions, _ = json.JSONDecoder().raw_decode(content)
            return sessions.get(entry.entry_id)
        except json.decoder.JSONDecodeError:
            _LOGGER.error("Failed to decode JSON session data in %s", file)
            return None
    return None


def _remove_legacy_token_file(hass: HomeAssistant) -> None:
    """Remove the legacy token file once tokens live in config entry data."""
    file = os.path.join(hass.config.config_dir, TOKEN_FILE_NAME)
    if os.path.isfile(file):
        _LOGGER.info("Removing legacy session token file %s", file)
        os.unlink(file)


def _async_persist_tokens(
    hass: HomeAssistant, entry: ConfigEntry, evnex_client: Evnex
) -> None:
    """Store the client's current tokens in the config entry if they changed."""
    tokens = {
        CONF_ID_TOKEN: evnex_client.id_token,
        CONF_REFRESH_TOKEN: evnex_client.refresh_token,
        CONF_ACCESS_TOKEN: evnex_client.access_token,
    }
    if any(entry.data.get(key) != value for key, value in tokens.items()):
        hass.config_entries.async_update_entry(entry, data={**entry.data, **tokens})


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entry to a newer version."""
    _LOGGER.debug(
        "Migrating Evnex config entry from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    if config_entry.version == 1:
        new_data = {**config_entry.data}
        new_minor_version = config_entry.minor_version

        if new_minor_version == 1:
            # 1.1 -> 1.2: entity registry unique_id migration
            # This was previously handled inside async_setup_entry; we handle it here
            # so the version is correctly recorded before setup proceeds.
            entity_registry = er.async_get(hass)

            @callback
            def _update_unique_id_1_2(entry: er.RegistryEntry) -> dict[str, str] | None:
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
                uuid_part = entry.unique_id[:36]
                remainder = entry.unique_id[36:]
                if (key := remainder) in replacements.get(entry.domain, []):
                    new_unique_id = entry.unique_id.replace(
                        f"{uuid_part}{key}",
                        f"{uuid_part}{replacements[entry.domain][key]}",
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
                    return {"new_unique_id": new_unique_id}
                return None

            await er.async_migrate_entries(
                hass, config_entry.entry_id, _update_unique_id_1_2
            )
            new_minor_version = 2

        if new_minor_version == 2:
            # 1.2 -> 1.3: migrate auth tokens from evnex_session.json into config entry data
            _LOGGER.info(
                "Migrating Evnex auth tokens from file storage to config entry data"
            )
            tokens = await hass.async_add_executor_job(
                _read_tokens_from_file, hass, config_entry
            )
            if tokens:
                new_data[CONF_ID_TOKEN] = tokens.get(CONF_ID_TOKEN)
                new_data[CONF_REFRESH_TOKEN] = tokens.get(CONF_REFRESH_TOKEN)
                new_data[CONF_ACCESS_TOKEN] = tokens.get(CONF_ACCESS_TOKEN)
                _LOGGER.info("Successfully migrated auth tokens into config entry")
            else:
                _LOGGER.info(
                    "No existing token file found; tokens will be populated on next authentication"
                )
                new_data.setdefault(CONF_ID_TOKEN, None)
                new_data.setdefault(CONF_REFRESH_TOKEN, None)
                new_data.setdefault(CONF_ACCESS_TOKEN, None)
            new_minor_version = 3

        hass.config_entries.async_update_entry(
            config_entry, data=new_data, minor_version=new_minor_version
        )

        # The token file may be shared by several config entries; remove it
        # only once every entry has its tokens in config entry data.
        if all(
            entry.minor_version >= 3
            for entry in hass.config_entries.async_entries(DOMAIN)
        ):
            await hass.async_add_executor_job(_remove_legacy_token_file, hass)

    _LOGGER.debug(
        "Migration of Evnex config entry to version %s.%s complete",
        config_entry.version,
        config_entry.minor_version,
    )
    return True


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

    # Load tokens from config entry data (migrated from file in async_migrate_entry)
    httpx_client = get_async_client(hass)

    try:
        evnex_client: Evnex = await hass.async_add_executor_job(
            Evnex,
            username,
            password,
            entry.data.get(CONF_ID_TOKEN),
            entry.data.get(CONF_REFRESH_TOKEN),
            entry.data.get(CONF_ACCESS_TOKEN),
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

    async def async_update_data(is_retry: bool = False) -> EvnexCoordinatorData:
        """Fetch data from EVNEX API"""

        data = EvnexCoordinatorData()

        try:
            _LOGGER.info("Getting evnex user detail")
            account: EvnexUserDetail = await evnex_client.get_user_detail()

            _async_persist_tokens(hass, entry, evnex_client)

            data.user = account

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
                data.charge_points_by_org[org.id] = [cp for cp in charge_points]
                data.org_briefs[org.id] = org
                _LOGGER.debug(f"Getting evnex org insights for {org.name}")
                daily_insights = await evnex_client.get_org_insight(
                    days=7, org_id=org.id
                )
                data.org_insights[org.id] = daily_insights

                for charge_point in charge_points:
                    # Map charge_point.id back to org.id
                    data.charge_point_to_org_map[charge_point.id] = org.id

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
                        data.connector_brief[
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
                            data.charge_point_override[charge_point.id] = (
                                charge_point_override
                            )
                        except ReadTimeout:
                            _LOGGER.warning(
                                "Read timeout prevented getting charge point override"
                            )
                    else:
                        _LOGGER.debug(
                            "Not getting charge point override as charge point is not ONLINE"
                        )

                    data.charge_point_brief[charge_point.id] = charge_point
                    data.charge_point_details[charge_point.id] = charge_point_detail
                    data.charge_point_sessions[charge_point.id] = charge_point_sessions

            return data
        except NotAuthorizedException as err:
            if not is_retry:
                _LOGGER.debug("Refreshing auth and trying again")
                try:
                    await hass.async_add_executor_job(evnex_client.authenticate)
                except MFAChallengeException as mfa_err:
                    # Password re-auth needs an MFA code, which only the user
                    # can provide; trigger the reauth flow.
                    raise ConfigEntryAuthFailed(
                        "Session expired and account requires MFA to sign in again"
                    ) from mfa_err
                except NotAuthorizedException as auth_err:
                    raise ConfigEntryAuthFailed(
                        "Stored credentials were rejected"
                    ) from auth_err
                _async_persist_tokens(hass, entry, evnex_client)
                return await async_update_data(is_retry=True)
            _LOGGER.warning(
                "EVNEX Session Token is invalid and failed attempt to re-login"
            )
            raise ConfigEntryAuthFailed(
                "Re-authentication succeeded but the API still rejects requests"
            ) from err
        except MFAChallengeException as err:
            # Raised when the client has no usable tokens and signing in with
            # the stored password requires an MFA code only the user can provide
            raise ConfigEntryAuthFailed(
                "Account requires MFA to sign in again"
            ) from err
        except Exception as err:
            _LOGGER.exception(
                f"Unhandled exception while updating evnex info {err=} {type(err)}"
            )
            raise UpdateFailed from err

    coordinator: DataUpdateCoordinator[EvnexCoordinatorData] = DataUpdateCoordinator(
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
