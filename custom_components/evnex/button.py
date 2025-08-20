import logging
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import EvnexChargerEntity
from evnex.api import Evnex
from evnex.schema.v3.charge_points import (
    EvnexChargePointDetail as EvnexChargePointDetailV3,
)

from evnex.schema.user import EvnexUserDetail

from evnex.schema.charge_points import EvnexChargePoint

from .const import DATA_CLIENT, DATA_COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class EvnexButtonSensorEntityDescription(ButtonEntityDescription):
    """Describes Mammotion button sensor entity."""

    press_fn: Callable[[Evnex, str, str], Awaitable[None]]


EVNEX_BUTTONS: tuple[EvnexButtonSensorEntityDescription, ...] = (
    EvnexButtonSensorEntityDescription(
        key="charger_stop_session",
        press_fn=lambda evnex_api, charger_id, org_id: evnex_api.stop_charge_point(
            charge_point_id=charger_id, org_id=org_id
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Evnex button sensor entity."""

    entities = []
    hass_data = hass.data[DOMAIN][config_entry.entry_id]
    evnex_api_client = hass_data[DATA_CLIENT]
    coordinator = hass_data[DATA_COORDINATOR]
    if not coordinator.data or not coordinator.data.get("user"):
        _LOGGER.warning(
            "Button setup: Coordinator data or user data not available yet."
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

            # entities.append(
            #     EvnexChargerOverrideSwitch(
            #         evnex_api_client, coordinator, charger_id, org_id
            #     )
            # )

            charge_point_detail_v3: EvnexChargePointDetailV3 | None = (
                coordinator.data.get("charge_point_details", {}).get(charger_id)
            )

            # Iterate through connectors of this charger
            if charge_point_detail_v3 and charge_point_detail_v3.connectors:
                for connector_detail_v3 in charge_point_detail_v3.connectors:
                    entities.append(
                        EvnexChargerButtonEntity(
                            evnex_api_client,
                            coordinator,
                            entity_description,
                            charger_id,
                            org_id,
                        )
                        for entity_description in EVNEX_BUTTONS
                    )

            else:
                _LOGGER.debug(
                    f"No V3 connector details found for charger {charger_id} in org {org_id} "
                    f"when setting up buttons."
                )


class EvnexChargerButtonEntity(EvnexChargerEntity, ButtonEntity):
    entity_description: EvnexButtonSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        api_client,
        coordinator,
        entity_description,
        charger_id,
        org_id,
    ) -> None:
        """Initialise the switch."""
        self.evnex = api_client

        super().__init__(
            coordinator=coordinator,
            charger_id=charger_id,
            org_id=org_id,
        )

        self.entity_description = entity_description
        self._attr_translation_key = entity_description.key

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.entity_description.press_fn(self.evnex, self.charger_id, self.org_id)
