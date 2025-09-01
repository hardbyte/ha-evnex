import logging
from evnex.schema.charge_points import (
    EvnexChargePoint,
)
from evnex.schema.v3.charge_points import (
    EvnexChargePointConnector,
    EvnexChargePointDetail,
)
from evnex.schema.org import EvnexOrgBrief
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN, NAME

_LOGGER = logging.getLogger(__name__)


class EvnexOrgEntity(CoordinatorEntity):
    """Base Entity for an Evnex Org Sensor"""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DataUpdateCoordinator, org_id: str | None = None
    ) -> None:
        """Initialize an Evnex Org"""
        super().__init__(coordinator)
        if org_id is None:
            # Ensure user and organisations data is present
            if coordinator.data.get("user") and coordinator.data["user"].organisations:
                org_id = coordinator.data["user"].organisations[0].id
            else:
                # Fallback or raise error if org_id cannot be determined,
                raise ValueError("Cannot determine default evnex organization ID")
        self.org_id = org_id
        if (
            not coordinator.data
            or not coordinator.data.get("org_briefs")
            or self.org_id not in coordinator.data["org_briefs"]
        ):
            _LOGGER.error(
                f"Organization brief for ID {self.org_id} not found in coordinator data. Available org_briefs: {coordinator.data.get('org_briefs')}"
            )
        self.org_brief: EvnexOrgBrief = coordinator.data["org_briefs"][org_id]

        self.device_name = self.org_brief.name
        self.device_id = self.org_brief.id
        self._attr_unique_id = f"{self.org_id}_{self.entity_description.key}"
        self._attr_translation_key = self.entity_description.key

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device_info of the org."""
        return DeviceInfo(
            configuration_url="https://evnex.io",
            identifiers={(DOMAIN, self.device_id)},
            name=self.device_name,
            manufacturer=NAME,
        )


class EvnexChargerEntity(CoordinatorEntity):
    """Base Entity for a specific evnex charger"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        charger_id: str,
        org_id: str,
        key: str | None = None,
    ) -> None:
        """Initialize the ChargePoint entity."""
        super().__init__(coordinator)
        self.org_id = org_id
        if not coordinator.data or charger_id not in coordinator.data.get(
            "charge_point_brief", {}
        ):
            _LOGGER.error(
                f"Charge point brief for ID {charger_id} (org {org_id}) not found."
            )
            raise ValueError(f"Charge point brief for ID {charger_id} not found.")
        self.charge_point_brief: EvnexChargePoint = coordinator.data[
            "charge_point_brief"
        ][charger_id]

        self.connector_brief_by_id = {}
        charge_point_detail_v3_data = coordinator.data.get(
            "charge_point_details", {}
        ).get(charger_id)
        if charge_point_detail_v3_data and charge_point_detail_v3_data.connectors:
            for connector_v3_brief in charge_point_detail_v3_data.connectors:
                self.connector_brief_by_id[connector_v3_brief.connectorId] = (
                    connector_v3_brief
                )

        self.charge_point_detail: EvnexChargePointDetail = coordinator.data[
            "charge_point_details"
        ][charger_id]

        if charger_id not in coordinator.data.get("charge_point_sessions", {}):
            _LOGGER.warning(
                f"Charge point sessions for charger {charger_id} (org {org_id}) not found, defaulting to empty list."
            )
            self.charge_point_sessions = []
        else:
            self.charge_point_sessions = coordinator.data["charge_point_sessions"][
                charger_id
            ]

        self.device_name = self.charge_point_brief.name
        self.charger_id = charger_id
        self.manufacturer = "evnex"
        self.short_charger_model = self.charge_point_brief.details.model
        self._attr_unique_id = f"{self.charger_id}{key}"
        self._attr_translation_key = key

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device_info of the org."""
        model = (
            self.charge_point_brief.details.model
            if self.charge_point_brief and self.charge_point_brief.details
            else "Unknown"
        )
        firmware = (
            self.charge_point_brief.details.firmware
            if self.charge_point_brief and self.charge_point_brief.details
            else "Unknown"
        )
        serial = (
            self.charge_point_brief.serial if self.charge_point_brief else "Unknown"
        )

        return DeviceInfo(
            configuration_url="https://evnex.io",
            identifiers={(DOMAIN, self.charger_id)},
            name=self.device_name,
            manufacturer=NAME,
            model=model,
            sw_version=firmware,
            serial_number=serial,
        )

    @property
    def charger_status(self) -> EvnexChargePointDetail:
        return self.coordinator.data.get("charge_point_details", {}).get(
            self.charger_id
        )

    @property
    def technical_info(self) -> EvnexChargePoint:
        return self.coordinator.data.get("charge_point_brief", {}).get(self.charger_id)


class EvnexChargePointConnectorEntity(EvnexChargerEntity):
    """Base Entity for a specific evnex charger's connector"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        charger_id: str,
        org_id: str,
        connector_id: str = "1",
        key: str | None = None,
    ) -> None:
        """Initialize the Charge Point Connector entity."""
        super().__init__(coordinator, charger_id=charger_id, org_id=org_id, key=key)
        self._attr_translation_key = key
        self.connector_id = connector_id

        self.connector_brief: EvnexChargePointConnector | None = (
            self.connector_brief_by_id.get(self.connector_id)
        )

        if not self.connector_brief:
            _LOGGER.warning(
                f"Connector ID {self.connector_id} for charger {charger_id} (org {org_id}) not found "
                f"in self.connector_brief_by_id. Available IDs: {list(self.connector_brief_by_id.keys())}. "
                f"Entity may be unavailable."
            )
