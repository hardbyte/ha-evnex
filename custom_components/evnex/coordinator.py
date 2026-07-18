"""DataUpdateCoordinator for the Evnex integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from evnex.api import Evnex
from evnex.errors import EvnexAuthError
from evnex.schema.charge_points import EvnexChargePoint, EvnexChargePointOverrideConfig
from evnex.schema.user import EvnexUserDetail
from evnex.schema.v3.charge_points import EvnexChargePointDetail

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from httpx import HTTPStatusError, ReadTimeout

from .const import DOMAIN
from .models import EvnexCoordinatorData

SCAN_INTERVAL = timedelta(minutes=5)

_LOGGER: logging.Logger = logging.getLogger(__package__)


class EvnexCoordinator(DataUpdateCoordinator[EvnexCoordinatorData]):
    """Coordinates fetching Evnex data from a single API endpoint."""

    def __init__(
        self, hass: HomeAssistant, client: Evnex, entry: EvnexConfigEntry
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = client

    async def _async_update_data(self) -> EvnexCoordinatorData:
        """Fetch data from EVNEX API"""

        data = EvnexCoordinatorData()

        try:
            _LOGGER.info("Getting evnex user detail")
            account: EvnexUserDetail = await self.client.get_user_detail()

            data.user = account

            for org in account.organisations:
                _LOGGER.info(
                    f"Getting evnex charge points for '{org.name}' (Org ID: {org.id}, Slug: {org.slug})"
                )
                charge_points: list[EvnexChargePoint] = list()
                try:
                    charge_points = await self.client.get_org_charge_points(org.id)
                except HTTPStatusError:
                    _LOGGER.info("Org ID not supported switching to Slug")
                    charge_points = await self.client.get_org_charge_points(org.slug)
                data.charge_points_by_org[org.id] = [cp for cp in charge_points]
                data.org_briefs[org.id] = org
                _LOGGER.debug(f"Getting evnex org insights for {org.name}")
                daily_insights = await self.client.get_org_insight(
                    days=7, org_id=org.id
                )
                data.org_insights[org.id] = daily_insights

                for charge_point in charge_points:
                    # Map charge_point.id back to org.id
                    data.charge_point_to_org_map[charge_point.id] = org.id

                    _LOGGER.debug(
                        f"Getting evnex charge point data for '{charge_point.name}'"
                    )
                    api_v3_response = await self.client.get_charge_point_detail_v3(
                        charge_point_id=charge_point.id
                    )
                    charge_point_detail: EvnexChargePointDetail = (
                        api_v3_response.data.attributes
                    )

                    for connector_brief in charge_point_detail.connectors:
                        data.connector_brief[
                            (charge_point.id, connector_brief.connectorId)
                        ] = connector_brief

                    _LOGGER.debug(
                        f"Getting evnex charge point sessions for '{charge_point.name}'"
                    )
                    charge_point_sessions = await self.client.get_charge_point_sessions(
                        charge_point_id=charge_point.id
                    )

                    # Only get the charge point override if the charge point is online!
                    if charge_point_detail.networkStatus == "ONLINE":
                        _LOGGER.debug(
                            f"Getting evnex charge point override for '{charge_point.name}'"
                        )
                        # Don't block data update if a read timeout encountered
                        try:
                            charge_point_override: EvnexChargePointOverrideConfig = (
                                await self.client.get_charge_point_override(
                                    charge_point_id=charge_point.id
                                )
                            )
                            data.charge_point_override[charge_point.id] = (
                                charge_point_override
                            )
                        except ReadTimeout:
                            _LOGGER.warning(
                                "Read timeout prevented getting charge point override"
                            )
                    else:
                        _LOGGER.debug(
                            "Not getting charge point override as charge point is not ONLINE"
                        )

                    data.charge_point_brief[charge_point.id] = charge_point
                    data.charge_point_details[charge_point.id] = charge_point_detail
                    data.charge_point_sessions[charge_point.id] = charge_point_sessions

            return data
        except EvnexAuthError as err:
            raise ConfigEntryAuthFailed("Evnex session is no longer valid") from err
        except Exception as err:
            _LOGGER.exception(
                f"Unhandled exception while updating evnex info {err=} {type(err)}"
            )
            raise UpdateFailed from err


@dataclass
class EvnexRuntimeData:
    """Data stored on the config entry at runtime."""

    client: Evnex
    coordinator: EvnexCoordinator


type EvnexConfigEntry = ConfigEntry[EvnexRuntimeData]
