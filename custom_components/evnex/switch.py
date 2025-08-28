import logging
from typing import Any, Callable, Awaitable
from dataclasses import dataclass
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


@dataclass(frozen=True, kw_only=True)
class EvnexSwitchEntityDescription(SwitchEntityDescription):
    """Class to describe a Evnex Switch entity."""

    is_on_func: Callable[[dict[str, Any], str], bool]
    on_func: Callable[[Evnex, str], Awaitable[None]]
    off_func: Callable[[Evnex, str], Awaitable[None]]


EVNEX_SWITCHES: tuple[EvnexSwitchEntityDescription, ...] = (
    EvnexSwitchEntityDescription(
        key="charger_charge_now",
        is_on_func=lambda data, charger_id: data.get("charge_point_override", {})
        .get(charger_id)
        .chargeNow,
        on_func=lambda evnex_api, charge_point_id: evnex_api.set_charge_point_override(
            charge_point_id=charge_point_id, charge_now=True
        ),
        off_func=lambda evnex_api, charge_point_id: evnex_api.set_charge_point_override(
            charge_point_id=charge_point_id, charge_now=False
        ),
    ),
)


class EvnexChargerSwitch(EvnexChargerEntity, SwitchEntity):
    entity_description: EvnexSwitchEntityDescription

    def __init__(
        self,
        api_client,
        coordinator,
        charger_id,
        org_id,
        entity_description: EvnexSwitchEntityDescription,
    ) -> None:
        """Initialise the switch."""
        super().__init__(
            coordinator=coordinator,
            charger_id=charger_id,
            org_id=org_id,
            key=entity_description.key,
        )
        self.evnex = api_client
        self.entity_description = entity_description
        self._attr_translation_key = entity_description.key

    @property
    def is_on(self):
        return self.entity_description.is_on_func(
            self.coordinator.data, self.charger_id
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Charge now."""
        await self.entity_description.on_func(self.evnex, self.charger_id)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Don't charge now."""
        await self.entity_description.off_func(self.evnex, self.charger_id)
        await self.coordinator.async_request_refresh()


class EvnexChargerAvailabilitySwitch(EvnexChargePointConnectorEntity, SwitchEntity):
    def __init__(
        self, api_client, coordinator, charger_id, org_id, connector_id="1"
    ) -> None:
        """Initialise the switch."""
        super().__init__(
            coordinator=coordinator,
            charger_id=charger_id,
            org_id=org_id,
            connector_id=connector_id,
            key=f"connector_{connector_id}_availability",
        )
        self.evnex: Evnex = api_client
        self.entity_description = SwitchEntityDescription(
            key=f"connector_{connector_id}_availability",
        )
        self._attr_translation_key = f"connector_{connector_id}_availability"

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

            for entity_description in EVNEX_SWITCHES:
                entities.append(
                    EvnexChargerSwitch(
                        evnex_api_client,
                        coordinator,
                        charger_id,
                        org_id,
                        entity_description,
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
