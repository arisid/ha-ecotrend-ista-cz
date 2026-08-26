"""DataUpdateCoordinator for the ista EcoTrend (CZ / Nordic) integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EcotrendIstaCzApiClient, EcotrendIstaCzApiError, EcotrendIstaCzAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class EcotrendIstaCzCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches the meter list from ista on a schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: EcotrendIstaCzApiClient,
        update_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry.title})",
            update_interval=update_interval,
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            meters = await self.client.async_get_meters()
        except EcotrendIstaCzAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EcotrendIstaCzApiError as err:
            raise UpdateFailed(str(err)) from err

        meters_by_id: dict[str, dict[str, Any]] = {}
        for meter in meters:
            meter_id = meter.get("METER_ID")
            if meter_id is None:
                continue
            # METER_ID comes back as a float (e.g. 39894635894.0) - normalise to a clean string.
            key = str(int(meter_id))
            meters_by_id[key] = meter

        return {
            "meters": meters_by_id,
            "user_info": self.client.user_info,
        }
