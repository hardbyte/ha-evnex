"""Number platform for ocpp."""
from __future__ import annotations

import logging
from dataclasses import dataclass


from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    RestoreNumber,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.evnex import DATA_CLIENT, DATA_COORDINATOR, DOMAIN
from custom_components.evnex.const import DATA_UPDATED
from custom_components.evnex.entity import EvnexChargePointConnectorEntity
from evnex.api import Evnex
from evnex.schema.charge_points import EvnexChargePointLoadSchedule

_LOGGER = logging.getLogger(__name__)


@dataclass
class EvnexNumberDescription(NumberEntityDescription):
    """Class to describe a Number entity."""

    initial_value: float | None = None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number sliders."""
    entities = []

    evnex_api_client = hass.data[DOMAIN][config_entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][config_entry.entry_id][DATA_COORDINATOR]

    brief = coordinator.data["charge_point_brief"]
    for charger_id in brief:
        connector_brief = coordinator.data["connector_brief"]
        description = EvnexNumberDescription(
            key="charger_maximum_current",
            name="Charger Maximum Current",
            icon="mdi:ev-station",
            initial_value=connector_brief[(charger_id, "1")].maxAmperage,
            native_min_value=0,
            native_max_value=connector_brief[(charger_id, "1")].maxAmperage,
            native_step=1,
        )
        entities.append(
            EvnexNumber(evnex_api_client, coordinator, charger_id, description)
        )

    async_add_entities(entities)


class EvnexNumber(EvnexChargePointConnectorEntity, RestoreNumber, NumberEntity):
    """Individual slider for setting charge rate."""

    entity_description: EvnexNumberDescription

    def __init__(self, api_client, coordinator, charger_id, description):
        """Initialize a Number instance."""
        self.evnex: Evnex = api_client
        self.entity_description = description
        self._attr_native_value = self.entity_description.initial_value
        self._attr_should_poll = False

        super().__init__(coordinator=coordinator, charger_id=charger_id)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if restored := await self.async_get_last_number_data():
            self._attr_native_value = restored.native_value
        async_dispatcher_connect(
            self.hass, DATA_UPDATED, self._schedule_immediate_update
        )

    @callback
    def _schedule_immediate_update(self):
        self.async_schedule_update_ha_state(True)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return not self.coordinator.data["charge_point_brief"][self.charger_id] == "OFFLINE"  # type: ignore [no-any-return]

    async def async_set_native_value(self, value):
        """Set new value."""
        num_value = float(value)
        _LOGGER.info(f"Setting current to {num_value}A")

        resp = await self.evnex.set_charger_load_profile(
            self.charger_id,
            charging_profile_periods=[{"limit": num_value, "start": 0}],
            enabled=True,
            duration=86400,
            units="A",
        )

        if isinstance(resp, EvnexChargePointLoadSchedule):
            self._attr_native_value = num_value
            self.async_write_ha_state()
        else:
            _LOGGER.warn(f"Failed request: {resp}")

        await self.coordinator.async_request_refresh()
