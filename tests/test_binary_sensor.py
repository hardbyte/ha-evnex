"""Tests for Evnex binary sensors."""

from unittest.mock import MagicMock

import pytest

from custom_components.evnex.binary_sensor import (
    EvnexConnectorChargingBinarySensor,
    EvnexConnectorPluggedInBinarySensor,
)


def _make_sensors(
    ocpp_status: str | None,
) -> tuple[EvnexConnectorPluggedInBinarySensor, EvnexConnectorChargingBinarySensor]:
    """Construct connector binary sensors with mocked coordinator data."""
    plugged_in = EvnexConnectorPluggedInBinarySensor.__new__(
        EvnexConnectorPluggedInBinarySensor
    )
    charging = EvnexConnectorChargingBinarySensor.__new__(
        EvnexConnectorChargingBinarySensor
    )

    coordinator = MagicMock()
    connector_brief = {}
    if ocpp_status is not None:
        connector = MagicMock()
        connector.ocppStatus = ocpp_status
        connector_brief[("cp-1", "1")] = connector
    coordinator.data.connector_brief = connector_brief

    for sensor in (plugged_in, charging):
        sensor.charger_id = "cp-1"
        sensor.connector_id = "1"
        sensor.coordinator = coordinator

    return plugged_in, charging


@pytest.mark.parametrize(
    ("ocpp_status", "plugged_in_state", "charging_state"),
    [
        ("Charging", True, True),
        ("SUSPENDED_EV", True, False),
        ("available", False, False),
        (None, None, None),
    ],
)
def test_connector_binary_sensor_states(
    ocpp_status: str | None,
    plugged_in_state: bool | None,
    charging_state: bool | None,
) -> None:
    plugged_in, charging = _make_sensors(ocpp_status)

    assert plugged_in.is_on is plugged_in_state
    assert charging.is_on is charging_state
