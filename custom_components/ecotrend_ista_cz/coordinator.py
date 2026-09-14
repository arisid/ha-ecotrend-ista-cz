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
from .statistics import extract_current_month_value

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
        # Live sensor entities register themselves here (see sensor.py) so
        # the reimport_history service can find them without needing an
        # entity registry lookup.
        self.entities: list[Any] = []

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

        await self._async_update_current_month_values(meters_by_id)

        return {
            "meters": meters_by_id,
            "user_info": self.client.user_info,
        }

    async def _async_update_current_month_values(
        self, meters_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """Best-effort: fetch each relevant meter's consumption-so-far for
        the current, still-in-progress calendar month directly from ista,
        and stash it under "_consumption_this_month" on that meter's dict
        (read by sensor.py as an extra_state_attribute).

        This is a plain live read straight from ista's own numbers - not
        anything computed by us - specifically so it matches what ista's
        own app shows for the current month, without going anywhere near
        Home Assistant's own (unreliable for an in-progress period)
        statistics "change" calculation. Runs once per regular poll
        (daily by default); failures here are logged and otherwise ignored,
        never allowed to fail the whole coordinator update - the meter
        reading itself is the important part and must keep working even if
        this extra, nice-to-have number can't be fetched right now.
        """
        for meter_id, meter in meters_by_id.items():
            meter_type = (meter.get("MeterType") or "").upper()
            if meter_type not in ("ENERGY", "HW", "CW"):
                continue
            try:
                history = await self.client.async_get_usage_history(meter_type)
            except EcotrendIstaCzApiError:
                _LOGGER.debug(
                    "Could not fetch this month's consumption-so-far for meter %s",
                    meter_id,
                    exc_info=True,
                )
                meter["_consumption_this_month"] = None
                continue

            meter["_consumption_this_month"] = extract_current_month_value(history)
