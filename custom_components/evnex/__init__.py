"""
Custom integration to integrate Evnex with Home Assistant.

"""

import json
import logging
import os

from evnex.api import Evnex
from evnex.auth import EvnexAuth, TokenSet

from homeassistant.core import HomeAssistant, callback
from homeassistant.const import CONF_PASSWORD, Platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.httpx_client import get_async_client

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ID_TOKEN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    ISSUE_URL,
    PLATFORMS,
    TOKEN_FILE_NAME,
    VERSION,
)
from .coordinator import EvnexCoordinator, EvnexConfigEntry, EvnexRuntimeData

_LOGGER: logging.Logger = logging.getLogger(__package__)


def _read_tokens_from_file(hass: HomeAssistant, entry: EvnexConfigEntry) -> dict | None:
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


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: EvnexConfigEntry
) -> bool:
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

        if new_minor_version == 3:
            # 1.3 -> 1.4: fold the flat token fields into a single TokenSet,
            # and stop storing the account password now that the library
            # persists rotated tokens via a callback instead of re-authenticating.
            _LOGGER.info("Migrating Evnex config entry to the new token storage format")
            token_set = TokenSet(
                id_token=new_data.pop(CONF_ID_TOKEN, None),
                refresh_token=new_data.pop(CONF_REFRESH_TOKEN, None),
                access_token=new_data.pop(CONF_ACCESS_TOKEN, None),
            )
            new_data["tokens"] = token_set.to_dict()
            new_data.pop(CONF_PASSWORD, None)
            new_minor_version = 4

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


async def async_setup_entry(hass: HomeAssistant, entry: EvnexConfigEntry) -> bool:
    """Load the saved entities."""
    _LOGGER.info(
        "Version %s is starting, if you have any issues please report them here: %s",
        VERSION,
        ISSUE_URL,
    )

    tokens = TokenSet.from_dict(entry.data.get("tokens") or {})

    async def on_token_update(tokens: TokenSet) -> None:
        """Persist rotated tokens to the config entry."""
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "tokens": tokens.to_dict()}
        )

    auth = EvnexAuth(tokens=tokens, on_token_update=on_token_update)
    client = Evnex(auth=auth, httpx_client=get_async_client(hass))

    coordinator = EvnexCoordinator(hass, client, entry)

    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = EvnexRuntimeData(client=client, coordinator=coordinator)

    # Setup components
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EvnexConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
