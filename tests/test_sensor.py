"""Tests for Evnex sensors."""

from unittest.mock import MagicMock

from custom_components.evnex.sensor import EvnexChargePortConnectorEnergyMeterSensor


def _make_energy_meter_sensor(*, raw_register: float | None):
    """Construct a connector energy sensor with mocked coordinator data."""
    sensor = EvnexChargePortConnectorEnergyMeterSensor.__new__(
        EvnexChargePortConnectorEnergyMeterSensor
    )
    sensor.charger_id = "cp-1"
    sensor.connector_id = "1"

    coordinator = MagicMock()
    connector = MagicMock()
    if raw_register is None:
        connector.meter = None
    else:
        connector.meter.raw_register = raw_register
    coordinator.data.connector_brief = {("cp-1", "1"): connector}
    sensor.coordinator = coordinator
    return sensor


def test_connector_energy_meter_converts_wh_to_kwh() -> None:
    sensor = _make_energy_meter_sensor(raw_register=12345.0)

    assert sensor.native_value == 12.345


def test_connector_energy_meter_is_unavailable_without_meter() -> None:
    sensor = _make_energy_meter_sensor(raw_register=None)

    assert sensor.native_value is None
