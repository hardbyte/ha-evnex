"""Number platform for ocpp."""

from __future__ import annotations

import logging
from dataclasses import dataclass


from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    RestoreNumber,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_UPDATED, DATA_CLIENT, DATA_COORDINATOR, DOMAIN
from .entity import EvnexChargePointConnectorEntity
from evnex.api import Evnex
from evnex.schema.charge_points import EvnexChargePointLoadSchedule
from evnex.schema.v3.charge_points import (
    EvnexChargePointDetail as EvnexChargePointDetailV3,
)


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class EvnexNumberDescription(NumberEntityDescription):
    """Class to describe a Number entity."""

    initial_value: float | None = None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number sliders."""
    entities = []
    evnex_api_client = hass.data[DOMAIN][config_entry.entry_id][DATA_CLIENT]
    coordinator = hass.data[DOMAIN][config_entry.entry_id][DATA_COORDINATOR]
    if not coordinator.data or not coordinator.data.get("user"):
        _LOGGER.warning(
            "Number setup: Coordinator data or user data not available yet."
        )
        return
    user_detail = coordinator.data["user"]
    all_org_charge_points_data = coordinator.data.get("charge_points_by_org", {})

    for org_brief in user_detail.organisations:
        org_id = org_brief.id
        charge_points_in_org = all_org_charge_points_data.get(org_id, [])

        for charge_point_obj in charge_points_in_org:
            charger_id = charge_point_obj.id
            charge_point_detail_v3: EvnexChargePointDetailV3 | None = (
                coordinator.data.get("charge_point_details", {}).get(charger_id)
            )

            if charge_point_detail_v3 and charge_point_detail_v3.connectors:
                for connector_v3_brief in charge_point_detail_v3.connectors:
                    connector_id = connector_v3_brief.connectorId
                    # connector_v3_brief is the EvnexChargePointConnector object

                    if connector_v3_brief.maxAmperage is not None:
                        description = EvnexNumberDescription(
                            key=f"connector_{connector_id}_maximum_current",  # Unique key
                            name=f"Connector {connector_id} Maximum Current",
                            icon="mdi:speedometer",  # Changed icon
                            initial_value=float(connector_v3_brief.maxAmperage),
                            native_min_value=0.0,  # Common minimum for EVSEs
                            native_max_value=float(connector_v3_brief.maxAmperage),
                            native_step=1.0,
                            # mode=NumberMode.SLIDER, # Optional: if you want a slider
                        )
                        entities.append(
                            EvnexNumber(
                                evnex_api_client,
                                coordinator,
                                charger_id,
                                org_id,
                                connector_id,
                                description,
                            )
                        )
                    else:
                        _LOGGER.debug(
                            f"Max amperage not available for charger {charger_id} connector {connector_id}"
                        )
            else:
                _LOGGER.debug(
                    f"No V3 connector details for charger {charger_id} in org {org_id} for number entities."
                )

    if entities:
        async_add_entities(entities)


class EvnexNumber(EvnexChargePointConnectorEntity, RestoreNumber, NumberEntity):
    """Individual slider for setting charge rate."""

    entity_description: EvnexNumberDescription

    def __init__(
        self,
        api_client,
        coordinator,
        charger_id,
        org_id,
        connector_id: str,
        description,
    ) -> None:
        """Initialize a Number instance."""
        self.evnex: Evnex = api_client
        self.entity_description = description
        self._attr_native_value = self.entity_description.initial_value
        self._attr_should_poll = False

        super().__init__(
            coordinator=coordinator,
            charger_id=charger_id,
            org_id=org_id,
            connector_id=connector_id,
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if restored := await self.async_get_last_number_data():
            self._attr_native_value = restored.native_value
        async_dispatcher_connect(
            self.hass, DATA_UPDATED, self._schedule_immediate_update
        )

    @callback
    def _schedule_immediate_update(self) -> None:
        self.async_schedule_update_ha_state(True)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if (
            not self.charge_point_brief
            or self.charge_point_brief.networkStatus == "OFFLINE"
        ):
            return False
        return super().available

    async def async_set_native_value(self, value) -> None:
        """Set new value."""
        num_value = float(value)
        _LOGGER.info(f"Setting current to {num_value}A")

        resp = await self.evnex.set_charger_load_profile(
            self.charger_id,
            charging_profile_periods=[{"limit": num_value, "start": 0}],
            enabled=True,
            duration=86400,
            units="A",
        )

        if isinstance(resp, EvnexChargePointLoadSchedule):
            self._attr_native_value = num_value
            self.async_write_ha_state()
        else:
            _LOGGER.warning(f"Failed request: {resp}")

        await self.coordinator.async_request_refresh()
