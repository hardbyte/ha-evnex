"""Binary sensor platform for evnex."""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EvnexConfigEntry, EvnexCoordinator
from .entity import EvnexChargePointConnectorEntity

_LOGGER = logging.getLogger(__name__)

PLUGGED_IN_STATES = {
    "preparing",
    "charging",
    "suspended_ev",
    "suspended_evse",
    "finishing",
}


class EvnexConnectorPluggedInBinarySensor(
    EvnexChargePointConnectorEntity, BinarySensorEntity
):
    """Report whether a vehicle is plugged into a connector."""

    entity_description = BinarySensorEntityDescription(
        key="connector_plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
    )

    def __init__(
        self,
        coordinator: EvnexCoordinator,
        charger_id: str,
        org_id: str,
        connector_id: str,
    ) -> None:
        super().__init__(
            coordinator,
            charger_id,
            org_id,
            connector_id,
            key=self.entity_description.key,
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether a vehicle is plugged into the connector."""
        connector = self.coordinator.data.connector_brief.get(
            (self.charger_id, self.connector_id)
        )
        if (
            connector is None
            or (ocpp_status := getattr(connector, "ocppStatus", None)) is None
        ):
            return None
        return ocpp_status.lower() in PLUGGED_IN_STATES


class EvnexConnectorChargingBinarySensor(
    EvnexChargePointConnectorEntity, BinarySensorEntity
):
    """Report whether a connector is charging a vehicle."""

    entity_description = BinarySensorEntityDescription(
        key="connector_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    )

    def __init__(
        self,
        coordinator: EvnexCoordinator,
        charger_id: str,
        org_id: str,
        connector_id: str,
    ) -> None:
        super().__init__(
            coordinator,
            charger_id,
            org_id,
            connector_id,
            key=self.entity_description.key,
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether the connector is charging a vehicle."""
        connector = self.coordinator.data.connector_brief.get(
            (self.charger_id, self.connector_id)
        )
        if (
            connector is None
            or (ocpp_status := getattr(connector, "ocppStatus", None)) is None
        ):
            return None
        return ocpp_status.lower() == "charging"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EvnexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = config_entry.runtime_data.coordinator

    entities: list[BinarySensorEntity] = []
    if not coordinator.data:
        _LOGGER.warning("Coordinator data not available for binary sensor setup")
        return

    charge_point_to_org_map = coordinator.data.charge_point_to_org_map
    for charger_id in coordinator.data.charge_point_brief:
        org_id_for_charger = charge_point_to_org_map.get(charger_id)
        if org_id_for_charger is None:
            _LOGGER.warning(
                f"Charger {charger_id} does not have an associated organization ID."
            )
            continue

        charge_point_detail_v3 = coordinator.data.charge_point_details.get(charger_id)
        if charge_point_detail_v3 and charge_point_detail_v3.connectors:
            for connector_detail_v3 in charge_point_detail_v3.connectors:
                connector_id = connector_detail_v3.connectorId
                entities.extend(
                    (
                        EvnexConnectorPluggedInBinarySensor(
                            coordinator,
                            charger_id,
                            org_id_for_charger,
                            connector_id,
                        ),
                        EvnexConnectorChargingBinarySensor(
                            coordinator,
                            charger_id,
                            org_id_for_charger,
                            connector_id,
                        ),
                    )
                )

    async_add_entities(entities)
