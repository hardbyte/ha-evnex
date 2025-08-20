import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


from .const import DATA_CLIENT, DATA_COORDINATOR, DOMAIN
from .entity import (
    EvnexChargePointConnectorEntity,
    EvnexChargerEntity,
)
from evnex.api import Evnex
from evnex.schema.v3.charge_points import (
    EvnexChargePointConnector,
    EvnexChargePointDetail as EvnexChargePointDetailV3,
)

from evnex.schema.user import EvnexUserDetail

from evnex.schema.charge_points import EvnexChargePoint

_LOGGER = logging.getLogger(__name__)


class EvnexChargerOverrideSwitch(EvnexChargerEntity, SwitchEntity):
    def __init__(self, api_client, coordinator, charger_id, org_id) -> None:
        """Initialise the switch."""
        self.evnex = api_client

        super().__init__(coordinator=coordinator, charger_id=charger_id, org_id=org_id)

    entity_description = SwitchEntityDescription(
        key="charger_charge_now_switch",
        name="Charge Now",
    )

    @property
    def icon(self):
        override = self.coordinator.data.get("charge_point_override", {}).get(
            self.charger_id
        )
        if override is None:
            return "network-strength-off-outline"

        charge_now = override.chargeNow
        return "mdi:check-network" if charge_now else "mdi:close-network"

    @property
    def is_on(self):
        override = self.coordinator.data.get("charge_point_override", {}).get(
            self.charger_id
        )
        return override is not None and override.chargeNow

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Charge now."""
        _LOGGER.debug(f"Enabling 'Charge Now' for charger {self.charger_id}")
        await self.evnex.set_charge_point_override(
            charge_point_id=self.charger_id, charge_now=True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Don't charge now."""
        _LOGGER.debug(f"Disabling 'Charge Now' for charger {self.charger_id}")
        await self.evnex.set_charge_point_override(
            charge_point_id=self.charger_id, charge_now=False
        )
        await self.coordinator.async_request_refresh()


class EvnexChargerAvailabilitySwitch(EvnexChargePointConnectorEntity, SwitchEntity):
    def __init__(
        self, api_client, coordinator, charger_id, org_id, connector_id="1"
    ) -> None:
        """Initialise the switch."""
        self.evnex: Evnex = api_client
        self.entity_description = SwitchEntityDescription(
            key=f"connector_{connector_id}_availability_switch",
            name=f"Connector {connector_id} Availability",
        )

        super().__init__(
            coordinator=coordinator,
            charger_id=charger_id,
            org_id=org_id,
            connector_id=connector_id,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        charger_brief = self.coordinator.data.get("charge_point_brief", {}).get(
            self.charger_id
        )
        if not charger_brief or charger_brief.networkStatus == "OFFLINE":
            return False
        return super().available  # Rely on CoordinatorEntity.available

    @property
    def icon(self) -> str:
        return "mdi:ev-station"

    @property
    def is_on(self):
        brief: EvnexChargePointConnector = self.connector_brief
        return brief is not None and brief.ocppStatus == "AVAILABLE"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Change to available ie Operative."""
        _LOGGER.info("Enabling 'Availability' switch")

        await self.evnex.enable_charger(
            org_id=self.org_id,
            charge_point_id=self.charger_id,
            connector_id=self.connector_id,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Change to unavailable ie Inoperative."""
        _LOGGER.info("Disabling 'Availability' switch")
        await self.evnex.disable_charger(
            org_id=self.org_id,
            charge_point_id=self.charger_id,
            connector_id=self.connector_id,
        )
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches."""
    entities = []
    hass_data = hass.data[DOMAIN][config_entry.entry_id]
    evnex_api_client = hass_data[DATA_CLIENT]
    coordinator = hass_data[DATA_COORDINATOR]
    if not coordinator.data or not coordinator.data.get("user"):
        _LOGGER.warning(
            "Switch setup: Coordinator data or user data not available yet."
        )
        return
    user_detail: EvnexUserDetail = coordinator.data["user"]
    all_org_charge_points_data: dict[str, list[EvnexChargePoint]] = (
        coordinator.data.get("charge_points", {})
    )

    for org_brief in user_detail.organisations:
        org_id = org_brief.id
        charge_points_in_org = all_org_charge_points_data.get(org_id, [])

        # This is EvnexChargePoint (v2 schema)
        for charge_point_obj in charge_points_in_org:
            charger_id = charge_point_obj.id

            entities.append(
                EvnexChargerOverrideSwitch(
                    evnex_api_client, coordinator, charger_id, org_id
                )
            )

            charge_point_detail_v3: EvnexChargePointDetailV3 | None = (
                coordinator.data.get("charge_point_details", {}).get(charger_id)
            )

            # Iterate through connectors of this charger
            if charge_point_detail_v3 and charge_point_detail_v3.connectors:
                for connector_detail_v3 in charge_point_detail_v3.connectors:
                    connector_id = connector_detail_v3.connectorId
                    entities.append(
                        EvnexChargerAvailabilitySwitch(
                            evnex_api_client,
                            coordinator,
                            charger_id,
                            org_id,
                            connector_id,
                        )
                    )
            else:
                _LOGGER.debug(
                    f"No V3 connector details found for charger {charger_id} in org {org_id} "
                    f"when setting up availability switches."
                )

    async_add_entities(entities)
