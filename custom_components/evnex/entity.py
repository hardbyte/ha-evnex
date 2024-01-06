from evnex.schema.charge_points import (
    EvnexChargePoint,
    EvnexChargePointConnector,
    EvnexChargePointDetail,
)
from evnex.schema.v3.charge_points import EvnexChargePointSession
from evnex.schema.org import EvnexOrgBrief
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN, NAME


class EvnexOrgEntity(CoordinatorEntity):
    """Base Entity for an Evnex Org Sensor"""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator, org_id: str = None):
        """Initialize an Evnex Org"""
        super().__init__(coordinator)
        if org_id is None:
            org_id = coordinator.data["user"].organisations[0].id
        self.org_id = org_id
        self.org_brief: EvnexOrgBrief = coordinator.data["org_briefs"][org_id]

        self.device_name = self.org_brief.name
        self.device_id = self.org_brief.id

    @property
    def _attr_unique_id(self):
        return self.org_id + self.entity_description.key

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

    def __init__(self, coordinator: DataUpdateCoordinator, charger_id: str):
        """Initialize the ChargePoint entity."""
        super().__init__(coordinator)

        self.charge_point_brief: EvnexChargePoint = coordinator.data[
            "charge_point_brief"
        ][charger_id]

        self.connector_brief_by_id = {
            brief.connectorId: brief for brief in self.charge_point_brief.connectors
        }

        self.charge_point_detail: EvnexChargePointDetail = coordinator.data[
            "charge_point_details"
        ][charger_id]
        self.charge_point_sessions: list[EvnexChargePointSession] = coordinator.data[
            "charge_point_sessions"
        ][charger_id]

        self.device_name = self.charge_point_brief.name
        self.charger_id = charger_id
        self.manufacturer = "evnex"
        self.short_charger_model = self.charge_point_brief.details.model

    @property
    def _attr_unique_id(self):
        try:
            return self.charger_id + self.entity_description.key
        except AttributeError:
            return self.charger_id + self.__class__.__name__

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device_info of the org."""
        return DeviceInfo(
            configuration_url="https://evnex.io",
            identifiers={(DOMAIN, self.charger_id)},
            name=self.device_name,
            manufacturer=NAME,
            model=self.charge_point_brief.details.model,
            sw_version=self.charge_point_brief.details.firmware,
            hw_version=self.charge_point_brief.serial,
        )

    @property
    def charger_status(self) -> EvnexChargePointDetail:
        return self.coordinator.data["charge_point_details"][self.charger_id]

    @property
    def technical_info(self) -> EvnexChargePoint:
        return self.coordinator.data["charge_point_brief"][self.charger_id]


class EvnexChargePointConnectorEntity(EvnexChargerEntity):
    """Base Entity for a specific evnex charger's connector"""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        charger_id: str,
        connector_id: str = "1",
    ):
        """Initialize the Charge Point Connector entity."""
        super().__init__(coordinator, charger_id=charger_id)
        self.connector_id = connector_id
        self.connector_brief: EvnexChargePointConnector = self.connector_brief_by_id[
            connector_id
        ]

    # Icon based on connector type? mdi:ev-plug-type2
    # @property
    # def device_info(self) -> DeviceInfo:
    #     """Return the device_info of the org."""
    #     return DeviceInfo(
    #         name='Connector',
    #         configuration_url="https://evnex.io",
    #         identifiers={(DOMAIN, f'{self.connector_brief.evseId}')},
    #         manufacturer=NAME,
    #         model=self.connector_brief.connectorType,
    #         via_device=(DOMAIN, f'{self.charger_id}')
    #     )
