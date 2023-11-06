import logging
from typing import Any

from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


from custom_components.evnex import DATA_CLIENT, DATA_COORDINATOR, DOMAIN
from custom_components.evnex.entity import (
    EvnexChargePointConnectorEntity,
    EvnexChargerEntity,
)
from evnex.api import Evnex
from evnex.schema.charge_points import EvnexChargePoint
from evnex.schema.v3.charge_points import (
    EvnexChargePointConnector,
    EvnexChargePointDetail,
)

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
        override = self.coordinator.data["charge_point_override"][self.charger_id]
        if override is None:
            return "network-strength-off-outline"

        charge_now = override.chargeNow
        return "mdi:check-network" if charge_now else "mdi:close-network"

    @property
    def is_on(self):
        override = self.coordinator.data["charge_point_override"][self.charger_id]
        return override is not None and override.chargeNow

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Charge now."""
        _LOGGER.info("Enabling 'Charge Now' switch")
        await self.evnex.set_charge_point_override(
            charge_point_id=self.charger_id, charge_now=True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Don't charge now."""
        _LOGGER.info("Disabling 'Charge Now' switch")
        await self.evnex.set_charge_point_override(
            charge_point_id=self.charger_id, charge_now=False
        )
        await self.coordinator.async_request_refresh()


class EvnexChargerAvailabilitySwitch(EvnexChargePointConnectorEntity, SwitchEntity):
    def __init__(self, api_client, coordinator, charger_id, connector_id="1"):
        """Initialise the switch."""
        self.evnex: Evnex = api_client

        super().__init__(
            coordinator=coordinator, charger_id=charger_id, connector_id=connector_id
        )

        self.entity_description = SwitchEntityDescription(
            key="_".join(["connector", self.connector_id, "availability_switch"]),
            name=f"Connector {self.connector_id} Availability",
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        charge_point_brief: EvnexChargePoint = self.coordinator.data[
            "charge_point_brief"
        ][self.charger_id]
        charge_point_details: EvnexChargePointDetail = self.coordinator.data[
            "charge_point_details"
        ][self.charger_id]

        return True
        # TODO

        # return not charge_point_brief == "OFFLINE"  # type: ignore [no-any-return]

    @property
    def icon(self):
        return "mdi:ev-station"

    @property
    def is_on(self):
        brief: EvnexChargePointConnector = self.coordinator.data["connector_brief"][
            (self.charger_id, self.connector_id)
        ]
        return brief is not None and brief.ocppStatus == "AVAILABLE"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Change to available ie Operative."""
        _LOGGER.info("Enabling 'Availability' switch")
        await self.evnex.enable_charger(
            charge_point_id=self.charger_id, connector_id=self.connector_id
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Change to unavailable ie Inoperative."""
        _LOGGER.info("Disabling 'Availability' switch")
        await self.evnex.disable_charger(
            charge_point_id=self.charger_id, connector_id=self.connector_id
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

    for charger_id in coordinator.data["charge_point_brief"]:
        entities.append(
            EvnexChargerOverrideSwitch(evnex_api_client, coordinator, charger_id)
        )
    for charger_id, connector_id in coordinator.data["connector_brief"]:
        entities.append(
            EvnexChargerAvailabilitySwitch(
                evnex_api_client, coordinator, charger_id, connector_id
            )
        )

    async_add_entities(entities)
