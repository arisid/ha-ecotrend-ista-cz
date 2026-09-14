"""Sensor platform for ista EcoTrend (CZ / Nordic)."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfEnergy, UnitOfVolume

from .const import CONF_ADDRESS, CONF_CONS_ID, CONF_HISTORY_IMPORTED, DOMAIN, METER_TYPE_ICONS
from .coordinator import EcotrendIstaCzCoordinator
from .statistics import async_backfill_usage_statistics

_LOGGER = logging.getLogger(__name__)

# API "Unit" field -> (HA unit, device_class)
_UNIT_MAP: dict[str, tuple[str, SensorDeviceClass | None]] = {
    "m3": (UnitOfVolume.CUBIC_METERS, None),  # device_class set separately from MeterType
    "kWh": (UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
    "MWh": (UnitOfEnergy.MEGA_WATT_HOUR, SensorDeviceClass.ENERGY),
}

_WATER_METER_TYPES = {"HW", "CW"}
_UNIT_CLASS_MAP = {"ENERGY": "energy", "HW": "volume", "CW": "volume"}


def _parse_date(value: str | None) -> date | None:
    """Parse ista's DD-MM-YYYY reading date into a date object."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except ValueError:
        return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # ista uses "3000-01-01" as a sentinel for "no deactivation date yet"
    # (i.e. the meter is still active) - surface that as None instead.
    if parsed.year >= 3000:
        return None
    return parsed


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up ista EcoTrend meter sensors from a config entry."""
    coordinator: EcotrendIstaCzCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        EcotrendIstaCzMeterSensor(coordinator, entry, meter_id)
        for meter_id in coordinator.data.get("meters", {})
    ]
    async_add_entities(entities)


class EcotrendIstaCzMeterSensor(CoordinatorEntity[EcotrendIstaCzCoordinator], SensorEntity):
    """Represents the latest reading of a single ista meter."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self, coordinator: EcotrendIstaCzCoordinator, entry: ConfigEntry, meter_id: str
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._meter_id = meter_id

        meter = self._meter
        self._attr_unique_id = f"{entry.entry_id}_{meter_id}"

        headline = meter.get("Headline") or meter.get("MeterText") or "Měřič"
        room = (meter.get("ROOM_DESCR") or "").strip()
        self._attr_name = f"{headline} - {room}" if room else headline

        meter_type = (meter.get("MeterType") or "").upper()
        self._attr_icon = METER_TYPE_ICONS.get(meter_type, "mdi:gauge")

        unit = meter.get("Unit")
        ha_unit, device_class = _UNIT_MAP.get(unit, (unit, None))
        self._attr_native_unit_of_measurement = ha_unit
        if meter_type in _WATER_METER_TYPES:
            self._attr_device_class = SensorDeviceClass.WATER
        elif device_class is not None:
            self._attr_device_class = device_class

    @property
    def _meter(self) -> dict[str, Any]:
        return self.coordinator.data.get("meters", {}).get(self._meter_id, {})

    async def async_added_to_hass(self) -> None:
        """Once this entity is registered (and self.entity_id is known),
        do a one-time backfill of its historical statistics from ista -
        for all three meter types confirmed against a real capture
        (energy, hot water, cold water - see api.py's _HISTORY_URLS).
        """
        await super().async_added_to_hass()
        self.coordinator.entities.append(self)
        await self._async_import_history()

    async def async_will_remove_from_hass(self) -> None:
        if self in self.coordinator.entities:
            self.coordinator.entities.remove(self)
        await super().async_will_remove_from_hass()

    async def _async_import_history(self, force: bool = False) -> bool:
        """Fetch and (re)import this meter's historical statistics.

        With ``force=False`` (the normal path, run once per meter from
        ``async_added_to_hass``), this is a no-op if already imported
        before. With ``force=True`` (used by the ``reimport_history``
        service), it re-fetches and re-imports regardless, reusing the
        already-authenticated API client - no fresh login involved, so it's
        safe to call anytime a past import needs correcting (e.g. after a
        code fix, or after a water meter gets physically replaced).
        """
        meter_type = (self._meter.get("MeterType") or "").upper()
        if meter_type not in ("ENERGY", "HW", "CW"):
            return False

        already_imported = self._entry.data.get(CONF_HISTORY_IMPORTED, [])
        if not force and self._meter_id in already_imported:
            return False

        current_reading = self._meter.get("Last_Meter_Reading")
        unit = self.native_unit_of_measurement
        if current_reading is None or not unit:
            return False

        active_since = None
        try:
            activation_raw = self._meter.get("Activation_date")
            if activation_raw:
                active_since = datetime.fromisoformat(activation_raw)
        except ValueError:
            active_since = None

        try:
            history = await self.coordinator.client.async_get_usage_history(meter_type)
            imported = await async_backfill_usage_statistics(
                self.hass,
                self.entity_id,
                self.name or "ista EcoTrend",
                unit,
                history,
                current_reading,
                active_since,
                unit_class=_UNIT_CLASS_MAP.get(meter_type),
            )
        except Exception:  # noqa: BLE001 - deliberately broad, see docstring
            # This covers both ista-side failures (EcotrendIstaCzApiError)
            # and anything going wrong on the HA/recorder side (e.g. the
            # recorder integration being disabled). Either way this is a
            # best-effort backfill: it must never take the actual meter
            # reading sensor down with it.
            _LOGGER.warning(
                "Nepodařilo se načíst/uložit historii spotřeby z ista pro "
                "%s - aktuální hodnoty tím nejsou dotčené, zkusí se to "
                "znovu při příštím restartu HA (nebo ruční akcí reimport_history).",
                self.entity_id,
                exc_info=True,
            )
            return False

        if imported and self._meter_id not in already_imported:
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={
                    **self._entry.data,
                    CONF_HISTORY_IMPORTED: [*already_imported, self._meter_id],
                },
            )
        return imported

    @property
    def available(self) -> bool:
        return super().available and self._meter_id in self.coordinator.data.get("meters", {})

    @property
    def native_value(self) -> float | None:
        return self._meter.get("Last_Meter_Reading")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        meter = self._meter
        inst_no = meter.get("INST_NO")
        if isinstance(inst_no, float) and inst_no.is_integer():
            inst_no = int(inst_no)
        return {
            "last_consumption": meter.get("Last_Meter_Consumption"),
            "consumption_this_month": meter.get("_consumption_this_month"),
            "reading_date": _parse_date(meter.get("Reading_date")),
            "meter_number": meter.get("METER_NO"),
            "room": meter.get("ROOM_DESCR"),
            "installation_number": inst_no,
            "activation_date": _parse_iso(meter.get("Activation_date")),
            "deactivation_date": _parse_iso(meter.get("Deactivation_date")),
        }

    @property
    def device_info(self) -> DeviceInfo:
        address = self._entry.data.get(CONF_ADDRESS)
        cons_id = self._entry.data.get(CONF_CONS_ID, self._entry.entry_id)
        return DeviceInfo(
            identifiers={(DOMAIN, str(cons_id))},
            name=f"ista EcoTrend - {address}" if address else "ista EcoTrend",
            manufacturer="ista",
            model="EcoTrend",
            configuration_url="https://ecotrend.ista.cz",
        )
