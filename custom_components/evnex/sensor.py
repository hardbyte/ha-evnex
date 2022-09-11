"""Sensor platform for evnex."""
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Union

from evnex.schema.charge_points import EvnexChargePoint
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    CURRENCY_DOLLAR,
    STATE_UNAVAILABLE,
    STATE_ON,
    STATE_OFF,
    TIME_SECONDS,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util.unit_system import UnitSystem

from .entity import EvnexChargePointConnectorEntity, EvnexOrgEntity, EvnexChargerEntity
from .const import DATA_CLIENT, DATA_COORDINATOR, DOMAIN


_LOGGER = logging.getLogger(__name__)


class EvnexOrgWidePowerUsageSensorToday(EvnexOrgEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="org_wide_power_usage_today",
        name="Total Power Usage Today",
        native_unit_of_measurement='Wh',
        icon="mdi:lightning-bolt-circle",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data['org_insights'][self.org_id][-1].powerUsage


class EvnexOrgWideChargeSessionsCountSensor(EvnexOrgEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="org_wide_charger_sessions_today",
        name="Charger sessions today",
        native_unit_of_measurement='sessions',
        icon="mdi:repeat_one",
        state_class=SensorStateClass.TOTAL_INCREASING,
    )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data['org_insights'][self.org_id][-1].sessions

    @property
    def last_reset(self):
        """Return the state of the sensor."""
        return self.coordinator.data['org_insights'][self.org_id][-1].startDate


class EvnexChargerChargingStatusSensor(EvnexChargerEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="charger_status",
        name="Charging Status",
        icon="mdi:lightning-bolt",
    )

    @property
    def native_value(self):
        charger_brief: EvnexChargePoint = self.coordinator.data['charge_point_brief'][self.charger_id]
        return charger_brief.connectors[0].status


class EvnexChargerNetworkStatusSensor(EvnexChargerEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="charger_network_status",
        name="Network Status",
        icon="mdi:wifi",
    )

    @property
    def native_value(self):
        charger_brief: EvnexChargePoint = self.coordinator.data['charge_point_brief'][self.charger_id]
        return charger_brief.networkStatus


class EvnexChargePortConnectorStatusSensor(EvnexChargePointConnectorEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="connector_status",
        name="Charging Status",
        icon="mdi:lightning-bolt",
    )

    @property
    def native_value(self):
        brief = self.coordinator.data['connector_brief'][(self.charger_id, self.connector_id)]
        return brief.status


class EvnexChargePortConnectorVoltageSensor(EvnexChargePointConnectorEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="connector_voltage",
        name="Voltage",
        native_unit_of_measurement=SensorDeviceClass.VOLTAGE,
        icon="mdi:lightning-bolt",
        state_class=SensorStateClass.MEASUREMENT,
    )

    @property
    def native_value(self):
        brief = self.coordinator.data['connector_brief'][(self.charger_id, self.connector_id)]
        return brief.voltage


class EvnexChargePortConnectorPowerSensor(EvnexChargePointConnectorEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="connector_power",
        name="Metered Power",
        native_unit_of_measurement=SensorDeviceClass.POWER,
        icon="mdi:transmission-tower",
        state_class=SensorStateClass.MEASUREMENT,
    )

    @property
    def native_value(self):
        brief = self.coordinator.data['connector_brief'][(self.charger_id, self.connector_id)]
        return brief.meter.power


class EvnexChargePortConnectorFrequencySensor(EvnexChargePointConnectorEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="connector_frequency",
        name="Metered Power Frequency",
        native_unit_of_measurement=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    )

    @property
    def native_value(self):
        brief = self.coordinator.data['connector_brief'][(self.charger_id, self.connector_id)]
        return brief.meter.power


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""

    #client = hass.data[DOMAIN][config_entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][config_entry.entry_id][DATA_COORDINATOR]

    entities: list[SensorEntity] = []

    # Create an Evnex Org Sensor showing org wide weekly summary of powerUsage, charging sessions, cost
    entities.append(EvnexOrgWidePowerUsageSensorToday(coordinator=coordinator))
    entities.append(EvnexOrgWideChargeSessionsCountSensor(coordinator=coordinator))

    for charger_id in coordinator.data['charge_point_brief']:

        entities.append(EvnexChargerChargingStatusSensor(coordinator, charger_id))
        entities.append(EvnexChargerNetworkStatusSensor(coordinator, charger_id))

        charger_brief = coordinator.data['charge_point_brief'][charger_id]
        for connector_brief in charger_brief.connectors:
            connector_id = connector_brief.connectorId

            entities.append(EvnexChargePortConnectorStatusSensor(coordinator, charger_id, connector_id))
            entities.append(EvnexChargePortConnectorVoltageSensor(coordinator, charger_id, connector_id))
            entities.append(EvnexChargePortConnectorPowerSensor(coordinator, charger_id, connector_id))

    async_add_entities(entities)
