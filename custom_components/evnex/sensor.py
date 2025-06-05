"""Sensor platform for evnex."""
import datetime
import logging

from evnex.schema.charge_points import EvnexChargePoint
from evnex.schema.v3.charge_points import EvnexChargePointSession

from homeassistant.const import UnitOfElectricCurrent

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfFrequency,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant

from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EvnexChargePointConnectorEntity, EvnexOrgEntity, EvnexChargerEntity
from .const import DATA_COORDINATOR, DOMAIN


_LOGGER = logging.getLogger(__name__)

MAX_SESSIONS_IN_ATTRIBUTES = 10  # Configurable: Number of recent sessions to store


class EvnexOrgWidePowerUsageSensorToday(EvnexOrgEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="org_wide_power_usage_today",
        name="Total Power Usage Today",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        icon="mdi:lightning-bolt-circle",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        org_insights = self.coordinator.data.get("org_insights", {}).get(self.org_id)
        if org_insights and len(org_insights) > 0:
            return org_insights[-1].powerUsage
        return None

    @property
    def last_reset(self):
        org_insights = self.coordinator.data.get("org_insights", {}).get(self.org_id)
        if org_insights and len(org_insights) > 0:
            return org_insights[-1].startDate
        return None


class EvnexOrgWideChargeSessionsCountSensor(EvnexOrgEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="org_wide_charger_sessions_today",
        name="Charger sessions today",
        native_unit_of_measurement="sessions",
        icon="mdi:repeat_one",
        state_class=SensorStateClass.TOTAL,
    )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        org_insights = self.coordinator.data.get("org_insights", {}).get(self.org_id)
        if org_insights and len(org_insights) > 0:
            return org_insights[-1].sessions
        return None

    @property
    def last_reset(self):
        return self.coordinator.data["org_insights"][self.org_id][-1].startDate


class EvnexOrgTierSensor(EvnexOrgEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="org_tier",
        name="Organisation tier",
        icon="mdi:warehouse",
    )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.org_brief:
            return self.org_brief.tier
        return None


class EvnexChargerNetworkStatusSensor(EvnexChargerEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="charger_network_status",
        name="Network Status",
        icon="mdi:wifi",
    )

    @property
    def native_value(self):
        if self.charge_point_brief:
            return self.charge_point_brief.networkStatus
        return None


class EvnexChargerSessionEnergy(EvnexChargerEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="session_energy",
        name="Session Energy Added",
        icon="mdi:lightning-bolt-circle",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    )

    @property
    def native_value(self):
        sessions = self.coordinator.data.get("charge_point_sessions", {}).get(self.charger_id)
        if sessions and len(sessions) > 0:
            latest_session: EvnexChargePointSession = sessions[0]
            if latest_session.attributes and latest_session.attributes.endDate is None:  # Active session
                if latest_session.attributes.totalPowerUsage is not None:
                    return latest_session.attributes.totalPowerUsage
        return 0.0


class EvnexChargerSessionCost(EvnexChargerEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="session_cost",
        name="Charge Cost",
        icon="mdi:cash-multiple",
        # native_unit_of_measurement=CURRENCY_DOLLAR,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
    )

    @property
    def native_value(self):
        sessions = self.coordinator.data.get("charge_point_sessions", {}).get(self.charger_id)
        if sessions and len(sessions) > 0:
            latest_session: EvnexChargePointSession = sessions[0]
            if latest_session.attributes and latest_session.attributes.endDate is None:  # Active session
                if latest_session.attributes.totalCost and latest_session.attributes.totalCost.amount is not None:
                    return latest_session.attributes.totalCost.amount
        return 0.0


class EvnexChargerSessionTime(EvnexChargerEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="session_time",
        name="Charge Time",
        icon="mdi:timer",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
    )

    @property
    def native_value(self):
        sessions = self.coordinator.data.get("charge_point_sessions", {}).get(self.charger_id)
        if sessions and len(sessions) > 0:
            latest_session: EvnexChargePointSession = sessions[0]
            if latest_session.attributes and latest_session.attributes.startDate:
                start_date = latest_session.attributes.startDate
                if latest_session.attributes.endDate is None:
                    if start_date.tzinfo is None:
                        start_date = start_date.replace(tzinfo=datetime.timezone.utc)
                    now = datetime.datetime.now(datetime.timezone.utc)
                    return (now - start_date).total_seconds()
                elif latest_session.attributes.endDate:
                    end_date = latest_session.attributes.endDate
                    if start_date.tzinfo is None: start_date = start_date.replace(tzinfo=datetime.timezone.utc)
                    if end_date.tzinfo is None: end_date = end_date.replace(tzinfo=datetime.timezone.utc)
                    return (end_date - start_date).total_seconds()
        return None

class EvnexChargerLastSessionStartTime(EvnexChargerEntity, SensorEntity):
    entity_description = SensorEntityDescription(
        key="session_start_time",
        name="Last Session Start",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:progress-clock",
    )

    @property
    def native_value(self):
        sessions = self.coordinator.data.get("charge_point_sessions", {}).get(self.charger_id)
        if sessions and len(sessions) > 0:
            latest_session: EvnexChargePointSession = sessions[0]
            if latest_session.attributes and latest_session.attributes.startDate:
                return latest_session.attributes.startDate
        return None




class EvnexChargerSessionHistorySensor(EvnexChargerEntity, SensorEntity):
    """Sensor to expose recent charging session history."""

    entity_description = SensorEntityDescription(
        key="charger_session_history",
        name="Session History",  # Will be prefixed with device name by HA
        icon="mdi:history",
    )

    @property
    def native_value(self):
        """Return the state of the sensor (e.g., count of recent sessions)."""
        sessions = self._get_formatted_sessions()
        return len(sessions)

    @property
    def extra_state_attributes(self):
        """Return the recent session data as attributes."""
        attributes = super().extra_state_attributes or {}
        attributes["sessions"] = self._get_formatted_sessions()
        # You could also add the timestamp of the absolute latest session start/end here if useful
        # Or the total energy/cost from these displayed sessions
        return attributes

    def _get_formatted_sessions(self) -> list[dict]:
        """Helper to get and format recent sessions."""
        # self.charge_point_sessions is already available from EvnexChargerEntity,
        # populated with List[EvnexChargePointSession]

        if not self.charge_point_sessions:
            return []

        formatted_sessions = []
        # API returns sessions newest first, so take the first N sessions
        for session_data in self.charge_point_sessions[:MAX_SESSIONS_IN_ATTRIBUTES]:
            attrs = session_data.attributes
            if not attrs:
                continue

            session_entry = {
                "session_id": session_data.id,
                "start_time": attrs.startDate.isoformat() if attrs.startDate else None,
                "end_time": attrs.endDate.isoformat() if attrs.endDate else None,
                "status": attrs.sessionStatus,  # e.g., "COMPLETED", "ACTIVE"
                "connector_id": attrs.connectorId,
                "energy_wh": attrs.totalPowerUsage,  # This is already in Wh
                "duration_seconds": None,
                "cost": None,
                "currency": None,
            }

            if attrs.startDate and attrs.endDate:
                # Ensure they are timezone-aware for correct subtraction
                start = attrs.startDate
                end = attrs.endDate
                if start.tzinfo is None: start = start.replace(tzinfo=datetime.timezone.utc)
                if end.tzinfo is None: end = end.replace(tzinfo=datetime.timezone.utc)
                session_entry["duration_seconds"] = (end - start).total_seconds()
            elif attrs.startDate and attrs.endDate is None:  # Active session
                start = attrs.startDate
                if start.tzinfo is None: start = start.replace(tzinfo=datetime.timezone.utc)
                now = datetime.datetime.now(datetime.timezone.utc)
                session_entry["duration_seconds"] = (now - start).total_seconds()

            if attrs.totalCost:
                session_entry["cost"] = attrs.totalCost.amount
                session_entry["currency"] = attrs.totalCost.currency

            # You can add more fields if needed, e.g., attrs.reason for session end

            formatted_sessions.append(session_entry)

        return formatted_sessions


class EvnexChargePortConnectorStatusSensor(
    EvnexChargePointConnectorEntity, SensorEntity
):
    entity_description = SensorEntityDescription(
        key="connector_status",
        name="Connector Status",
    )

    @property
    def native_value(self):
        if self.connector_brief:
            return self.connector_brief.ocppStatus
        return None

    @property
    def icon(self):
        """Return the icon of the sensor."""
        icon = "mdi:help-circle"
        status = self.native_value
        if status == "AVAILABLE":
            icon = "mdi:power-plug-off"
        elif status == "PREPARING":
            return "mdi:power-plug-outline"
        elif status == "OCCUPIED" or status == "SUSPENDED_EVSE" or status == "SUSPENDED_EV":
            icon = "mdi:power-plug"
        elif status == "CHARGING":
            icon = "mdi:battery-positive"
        elif status == "FINISHING":
            icon = "mdi:power-plug-off-outline"
        elif status == "RESERVED":
            icon = "mdi:timer-sand"
        elif status == "UNAVAILABLE":
            icon = "mdi:lan-disconnect"
        elif status == "FAULTED":
            icon = "mdi:alert-circle"
        return icon


class EvnexChargePortConnectorVoltageSensor(
    EvnexChargePointConnectorEntity, SensorEntity
):
    entity_description = SensorEntityDescription(
        key="connector_voltage",
        name="VoltageL1N",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        state_class=SensorStateClass.MEASUREMENT,
    )

    @property
    def native_value(self):
        if self.connector_brief and self.connector_brief.meter:
            return self.connector_brief.meter.voltageL1N
        return None


class EvnexChargePortConnectorCurrentSensor(
    EvnexChargePointConnectorEntity, SensorEntity
):
    entity_description = SensorEntityDescription(
        key="connector_current",
        name="CurrentL1",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:lightning-bolt",
        state_class=SensorStateClass.MEASUREMENT,
    )

    @property
    def native_value(self):
        if self.connector_brief and self.connector_brief.meter:
            return self.connector_brief.meter.currentL1
        return None


class EvnexChargePortConnectorPowerSensor(
    EvnexChargePointConnectorEntity, SensorEntity
):
    entity_description = SensorEntityDescription(
        key="connector_power",
        name="Metered Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        icon="mdi:flash-triangle",
        state_class=SensorStateClass.MEASUREMENT,
    )

    @property
    def native_value(self):
        if self.connector_brief and self.connector_brief.meter and self.connector_brief.meter.power is not None:
            return self.connector_brief.meter.power / 1000
        return None


class EvnexChargePortConnectorFrequencySensor(
    EvnexChargePointConnectorEntity, SensorEntity
):
    entity_description = SensorEntityDescription(
        key="connector_frequency",
        name="Metered Frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        icon="mdi:sine-wave",
        state_class=SensorStateClass.MEASUREMENT,
    )

    @property
    def native_value(self):
        if self.connector_brief and self.connector_brief.meter:
            return self.connector_brief.meter.frequency
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""

    # client = hass.data[DOMAIN][config_entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][config_entry.entry_id][DATA_COORDINATOR]

    entities: list[SensorEntity] = []
    if not coordinator.data:
        _LOGGER.warning("Coordinator data not available for sensor setup")
        return

    charge_point_to_org_map = coordinator.data.get("charge_point_to_org_map", {})

    # Org Sensors
    # This Sensor shows org wide weekly summary of powerUsage, charging sessions, cost
    for org_id in coordinator.data.get("org_briefs", {}).keys():
        entities.append(EvnexOrgWidePowerUsageSensorToday(coordinator=coordinator, org_id=org_id))
        entities.append(EvnexOrgWideChargeSessionsCountSensor(coordinator=coordinator, org_id=org_id))
        entities.append(EvnexOrgTierSensor(coordinator=coordinator, org_id=org_id))

    # Charger and Connector Sensors
    for charger_id, charger_brief_obj in coordinator.data.get("charge_point_brief", {}).items():
        org_id_for_charger = charge_point_to_org_map.get(charger_id)
        if org_id_for_charger is None:
            _LOGGER.warning(f"Charger {charger_id} does not have an associated organization ID.")
            continue

        # Charger-level sensors
        entities.append(EvnexChargerNetworkStatusSensor(coordinator, charger_id, org_id_for_charger))
        entities.append(EvnexChargerSessionEnergy(coordinator, charger_id, org_id_for_charger))
        entities.append(EvnexChargerSessionCost(coordinator, charger_id, org_id_for_charger))
        entities.append(EvnexChargerSessionTime(coordinator, charger_id, org_id_for_charger))
        entities.append(EvnexChargerLastSessionStartTime(coordinator, charger_id, org_id_for_charger))

        entities.append(EvnexChargerSessionHistorySensor(coordinator, charger_id, org_id_for_charger))

        # Connector-level sensors
        charge_point_detail_v3 = coordinator.data.get("charge_point_details", {}).get(charger_id)
        if charge_point_detail_v3 and charge_point_detail_v3.connectors:
            for connector_detail_v3 in charge_point_detail_v3.connectors:
                connector_id = connector_detail_v3.connectorId

                entities.append(
                    EvnexChargePortConnectorStatusSensor(
                        coordinator, charger_id, org_id_for_charger, connector_id
                    )
                )
                entities.append(
                    EvnexChargePortConnectorVoltageSensor(
                        coordinator, charger_id, org_id_for_charger, connector_id
                    )
                )
                entities.append(
                    EvnexChargePortConnectorCurrentSensor(
                        coordinator, charger_id, org_id_for_charger, connector_id
                    )
                )
                entities.append(
                    EvnexChargePortConnectorPowerSensor(
                        coordinator, charger_id, org_id_for_charger, connector_id
                    )
                )
                entities.append(
                    EvnexChargePortConnectorFrequencySensor(
                        coordinator, charger_id, org_id_for_charger, connector_id
                    )
                )

    async_add_entities(entities)
