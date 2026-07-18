import logging
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EvnexConfigEntry
from .entity import EvnexChargerEntity, EvnexCoordinator
from evnex.api import Evnex

from evnex.schema.user import EvnexUserDetail

from evnex.schema.charge_points import EvnexChargePoint

from .const import CHARGER_SESSION_READY_STATES

_LOGGER = logging.getLogger(__name__)


def _is_charger_session_ready(
    coordinator: EvnexCoordinator, charger_id: str, connector_id: str
) -> bool:
    connector_brief = coordinator.data.connector_brief.get((charger_id, connector_id))

    if coordinator.data.charge_point_details[charger_id].networkStatus != "ONLINE":
        return False

    if connector_brief is not None:
        return connector_brief.ocppStatus in CHARGER_SESSION_READY_STATES
    return False


@dataclass(frozen=True, kw_only=True)
class EvnexButtonSensorEntityDescription(ButtonEntityDescription):
    """Describes Mammotion button sensor entity."""

    press_fn: Callable[[Evnex, str, str], Awaitable[None]]
    available: Callable[[EvnexCoordinator, str, str], bool]


EVNEX_BUTTONS: tuple[EvnexButtonSensorEntityDescription, ...] = (
    EvnexButtonSensorEntityDescription(
        key="charger_stop_session",
        available=lambda coordinator, charger_id, connector_id: (
            _is_charger_session_ready(coordinator, charger_id, connector_id)
        ),
        press_fn=lambda evnex_api, charge_point_id, org_id: evnex_api.stop_charge_point(
            charge_point_id=charge_point_id, org_id=org_id
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EvnexConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Evnex button sensor entity."""

    entities: list = []
    evnex_api_client = config_entry.runtime_data.client
    coordinator = config_entry.runtime_data.coordinator
    if not coordinator.data or not coordinator.data.user:
        _LOGGER.warning(
            "Button setup: Coordinator data or user data not available yet."
        )
        return
    user_detail: EvnexUserDetail = coordinator.data.user
    all_org_charge_points_data: dict[str, list[EvnexChargePoint]] = (
        coordinator.data.charge_points_by_org
    )

    for org_brief in user_detail.organisations:
        org_id = org_brief.id
        charge_points_in_org = all_org_charge_points_data.get(org_id, [])

        # This is EvnexChargePoint (v2 schema)
        for charge_point_obj in charge_points_in_org:
            charger_id = charge_point_obj.id
            entities.extend(
                EvnexChargerButtonEntity(
                    evnex_api_client,
                    coordinator,
                    entity_description,
                    charger_id,
                    org_id,
                )
                for entity_description in EVNEX_BUTTONS
            )

    async_add_entities(entities)


class EvnexChargerButtonEntity(EvnexChargerEntity, ButtonEntity):
    entity_description: EvnexButtonSensorEntityDescription

    def __init__(
        self,
        api_client,
        coordinator: EvnexCoordinator,
        entity_description: EvnexButtonSensorEntityDescription,
        charger_id: str,
        org_id,
    ) -> None:
        """Initialise the switch."""
        self.evnex = api_client

        super().__init__(
            coordinator=coordinator,
            key=entity_description.key,
            charger_id=charger_id,
            org_id=org_id,
        )

        self.entity_description = entity_description
        self._attr_translation_key = entity_description.key

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.entity_description.press_fn(self.evnex, self.charger_id, self.org_id)
        await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        return self.entity_description.available(self.coordinator, self.charger_id, "1")
