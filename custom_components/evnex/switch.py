import logging
from typing import Any

from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


from custom_components.evnex import DATA_CLIENT, DATA_COORDINATOR, DOMAIN
from custom_components.evnex.entity import EvnexChargerEntity


_LOGGER = logging.getLogger(__name__)


class EvnexChargerOverrideSwitch(EvnexChargerEntity, SwitchEntity):

    def __init__(self, api_client, coordinator, charger_id):
        """Initialise the switch."""
        self.evnex = api_client

        super().__init__(coordinator=coordinator, charger_id=charger_id)

    entity_description = SensorEntityDescription(
        key="charger_charge_now_switch",
        name="Charge Now",
    )

    @property
    def icon(self):
        override = self.coordinator.data['charge_point_override'][self.charger_id]
        if override is None:
            return 'network-strength-off-outline'

        charge_now = override.chargeNow
        return 'mdi:check-network' if charge_now else 'mdi:close-network'

    @property
    def is_on(self):
        override = self.coordinator.data['charge_point_override'][self.charger_id]
        return override is not None and override.chargeNow

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Charge now."""
        _LOGGER.info("Enabling 'Charge Now' switch")
        await self.evnex.set_charge_point_override(
            charge_point_id=self.charger_id,
            charge_now=True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Don't charge now."""
        _LOGGER.info("Disabling 'Charge Now' switch")
        await self.evnex.set_charge_point_override(
            charge_point_id=self.charger_id,
            charge_now=False
        )
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches."""
    entities = []

    evnex_api_client = hass.data[DOMAIN][config_entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][config_entry.entry_id][DATA_COORDINATOR]

    for charger_id in coordinator.data['charge_point_brief']:
        entities.append(EvnexChargerOverrideSwitch(evnex_api_client, coordinator, charger_id))

    async_add_entities(entities)
