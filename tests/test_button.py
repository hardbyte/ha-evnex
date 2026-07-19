"""Tests for the Evnex stop-session button.

The button intentionally stays available (its availability follows coordinator
health) so it does not log a spurious "pressed" event each time it would
otherwise reappear; the session-ready guard lives in async_press instead.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.evnex.button import EVNEX_BUTTONS, EvnexChargerButtonEntity


def _make_entity(*, ready: bool) -> EvnexChargerButtonEntity:
    # Bypass the heavy EvnexChargerEntity.__init__; async_press only needs
    # these attributes.
    entity = EvnexChargerButtonEntity.__new__(EvnexChargerButtonEntity)
    entity.evnex = MagicMock()
    entity.evnex.stop_charge_point = AsyncMock()
    entity.charger_id = "cp-1"
    entity.org_id = "org-1"
    entity.entity_description = EVNEX_BUTTONS[0]

    coordinator = MagicMock()
    coordinator.async_refresh = AsyncMock()
    detail = MagicMock()
    detail.networkStatus = "ONLINE" if ready else "OFFLINE"
    coordinator.data.charge_point_details = {"cp-1": detail}
    connector = MagicMock()
    connector.ocppStatus = "CHARGING" if ready else "AVAILABLE"
    coordinator.data.connector_brief = {("cp-1", "1"): connector}
    entity.coordinator = coordinator
    return entity


async def test_stop_button_raises_when_no_active_session() -> None:
    entity = _make_entity(ready=False)
    with pytest.raises(HomeAssistantError):
        await entity.async_press()
    entity.evnex.stop_charge_point.assert_not_called()


async def test_stop_button_stops_when_session_active() -> None:
    entity = _make_entity(ready=True)
    await entity.async_press()
    entity.evnex.stop_charge_point.assert_awaited_once_with(
        charge_point_id="cp-1", org_id="org-1"
    )
    entity.coordinator.async_refresh.assert_awaited_once()
