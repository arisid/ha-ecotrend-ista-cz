"""The ista EcoTrend (CZ / Nordic) integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EcotrendIstaCzApiClient
from .const import (
    CONF_LANGUAGE,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_LANGUAGE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_REIMPORT_HISTORY,
)
from .coordinator import EcotrendIstaCzCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ista EcoTrend (CZ / Nordic) from a config entry."""
    session = async_get_clientsession(hass)

    client = EcotrendIstaCzApiClient(
        session=session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        language=entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
    )

    scan_minutes = entry.options.get(
        CONF_SCAN_INTERVAL_MINUTES, int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)
    )
    coordinator = EcotrendIstaCzCoordinator(
        hass, entry, client, update_interval=timedelta(minutes=scan_minutes)
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the (domain-wide, not per-entry) reimport_history service."""
    if hass.services.has_service(DOMAIN, SERVICE_REIMPORT_HISTORY):
        return

    async def _handle_reimport_history(call: ServiceCall) -> None:
        coordinators: list[EcotrendIstaCzCoordinator] = list(hass.data.get(DOMAIN, {}).values())
        if not coordinators:
            _LOGGER.warning("reimport_history zavoláno, ale žádná ista EcoTrend instance neběží")
            return

        results = []
        for coordinator in coordinators:
            for entity in list(coordinator.entities):
                try:
                    imported = await entity._async_import_history(force=True)  # noqa: SLF001
                except Exception:  # noqa: BLE001 - one entity's failure must not stop the rest
                    _LOGGER.exception("Reimport historie selhal pro %s", entity.entity_id)
                    continue
                results.append((entity.entity_id, imported))

        _LOGGER.info("ista EcoTrend reimport_history dokončen: %s", results)

    hass.services.async_register(DOMAIN, SERVICE_REIMPORT_HISTORY, _handle_reimport_history)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (e.g. scan interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_REIMPORT_HISTORY)
    return unload_ok
