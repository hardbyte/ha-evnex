"""Sensor platform for evnex."""
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Union

from evnex.schema.charge_points import EvnexChargePoint, EvnexChargePointDetail, EvnexChargePointTransaction
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ELECTRIC_POTENTIAL_VOLT, ENERGY_KILO_WATT_HOUR, ENERGY_WATT_HOUR, FREQUENCY_HERTZ, PERCENTAGE,
    CURRENCY_DOLLAR,
    POWER_KILO_WATT, POWER_WATT,
    STATE_UNAVAILABLE,
    STATE_ON,
    STATE_OFF,
    TIME_SECONDS,
)
from homeassistant.core import HomeAssistant

from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EvnexChargePointConnectorEntity, EvnexOrgEntity, EvnexChargerEntity
from .const import DATA_COORDINATOR, DOMAIN


_LOGGER = logging.getLogger(__name__)


class EvnexOrgWidePowerUsageSensorToday(EvnexOrgEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="org_wide_power_usage_today",
        name="Total Power Usage Today",
        native_unit_of_measurement=ENERGY_WATT_HOUR,
        icon="mdi:lightning-bolt-circle",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data['org_insights'][self.org_id][-1].powerUsage

    @property
    def last_reset(self):
        return self.coordinator.data['org_insights'][self.org_id][-1].startDate


class EvnexOrgWideChargeSessionsCountSensor(EvnexOrgEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="org_wide_charger_sessions_today",
        name="Charger sessions today",
        native_unit_of_measurement='sessions',
        icon="mdi:repeat_one",
        state_class=SensorStateClass.TOTAL,
    )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data['org_insights'][self.org_id][-1].sessions

    @property
    def last_reset(self):
        return self.coordinator.data['org_insights'][self.org_id][-1].startDate



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


class EvnexChargerSessionEnergy(EvnexChargerEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="session_energy",
        name="Session Energy Added",
        icon="mdi:lightning-bolt-circle",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=ENERGY_WATT_HOUR,
        unit_of_measurement=ENERGY_KILO_WATT_HOUR,
    )

    @property
    def native_value(self):
        t: EvnexChargePointTransaction = self.coordinator.data['charge_point_transactions'][self.charger_id][0]
        if t.endDate is None:
            return t.powerUsage
        else:
            return 0.0


class EvnexChargerSessionCost(EvnexChargerEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="session_cost",
        name="Charge Cost",
        icon="mdi:cash-multiple",
        #native_unit_of_measurement=CURRENCY_DOLLAR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.MONETARY,
    )

    @property
    def native_value(self):
        t: EvnexChargePointTransaction = self.coordinator.data['charge_point_transactions'][self.charger_id][0]
        if t.endDate is None:
            return t.electricityCost.cost
        else:
            return 0.0


class EvnexChargerSessionTime(EvnexChargerEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="session_time",
        name="Charge Time",
        icon="mdi:timer",
        native_unit_of_measurement=TIME_SECONDS,
        device_class=SensorDeviceClass.DURATION,
    )

    @property
    def native_value(self):
        t: EvnexChargePointTransaction = self.coordinator.data['charge_point_transactions'][self.charger_id][0]
        if t.endDate is None:
            return t.electricityCost.cost
        else:
            return 0.0


class EvnexChargerLastSessionStartTime(EvnexChargerEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="session_start_time",
        name="Last Session Start",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:progress-clock",
    )

    @property
    def native_value(self):
        t: EvnexChargePointTransaction = self.coordinator.data['charge_point_transactions'][self.charger_id][0]
        return t.startDate


class EvnexChargePortConnectorStatusSensor(EvnexChargePointConnectorEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="connector_status",
        name="Connector Status",
    )

    @property
    def native_value(self):
        brief = self.coordinator.data['connector_brief'][(self.charger_id, self.connector_id)]
        return brief.status

    @property
    def icon(self):
        """Return the icon of the sensor."""
        icon = None
        status = self.native_value
        if status == "AVAILABLE":
            icon = "mdi:power-plug-off"
        elif status == "OCCUPIED":
            icon = "mdi:power-plug"
        elif status == "CHARGING":
            icon = "mdi:battery-positive"
        return icon


class EvnexChargePortConnectorVoltageSensor(EvnexChargePointConnectorEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="connector_voltage",
        name="Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
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
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=POWER_WATT,
        unit_of_measurement=POWER_KILO_WATT,
        icon="mdi:lightening",
        state_class=SensorStateClass.MEASUREMENT,
    )

    @property
    def native_value(self):
        brief = self.coordinator.data['connector_brief'][(self.charger_id, self.connector_id)]
        return brief.meter.power


class EvnexChargePortConnectorFrequencySensor(EvnexChargePointConnectorEntity, SensorEntity):

    entity_description = SensorEntityDescription(
        key="connector_frequency",
        name="Metered Frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=FREQUENCY_HERTZ,
        icon="mdi:sine-wave",
        state_class=SensorStateClass.MEASUREMENT,
    )

    @property
    def native_value(self):
        brief = self.coordinator.data['connector_brief'][(self.charger_id, self.connector_id)]
        return brief.meter.frequency


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

        entities.append(EvnexChargerNetworkStatusSensor(coordinator, charger_id))

        entities.append(EvnexChargerSessionEnergy(coordinator, charger_id))
        entities.append(EvnexChargerSessionCost(coordinator, charger_id))
        entities.append(EvnexChargerSessionTime(coordinator, charger_id))
        entities.append(EvnexChargerLastSessionStartTime(coordinator, charger_id))

        charger_brief = coordinator.data['charge_point_brief'][charger_id]
        for connector_brief in charger_brief.connectors:
            connector_id = connector_brief.connectorId

            entities.append(EvnexChargePortConnectorStatusSensor(coordinator, charger_id, connector_id))
            entities.append(EvnexChargePortConnectorVoltageSensor(coordinator, charger_id, connector_id))
            entities.append(EvnexChargePortConnectorPowerSensor(coordinator, charger_id, connector_id))
            entities.append(EvnexChargePortConnectorFrequencySensor(coordinator, charger_id, connector_id))


    async_add_entities(entities)
