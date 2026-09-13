"""Backfill ista's historical monthly usage (energy + both water meters)
into Home Assistant's long-term statistics, so the Energy dashboard shows
real history instead of only what HA has recorded since the integration
was installed.

This targets the existing sensor's own statistic_id (its entity_id), using
``async_import_statistics`` with ``source="recorder"`` - the officially
supported way for an integration to backfill history for an entity it
already provides, as opposed to ``async_add_external_statistics`` which is
for statistics with no matching entity at all.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def _month_start_utc(date_str: str | None) -> datetime | None:
    """Turn ista's "end of month" ISO date string into a UTC, hour-aligned
    datetime for the *start* of that same month, in HA's configured
    timezone (statistics buckets are stored hourly and must be tz-aware).
    """
    if not date_str:
        return None
    try:
        parsed = datetime.fromisoformat(date_str)
    except ValueError:
        return None

    naive_month_start = parsed.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    local = naive_month_start.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_utc(local)


def build_statistics(
    history: list[dict[str, Any]],
    current_reading: float,
    active_since: datetime | None = None,
) -> list[StatisticData]:
    """Convert ista's monthly consumption deltas into a cumulative series
    anchored to the meter's current absolute reading.

    ista's "value" field is a per-month delta (consumption *that* month,
    in whatever unit the meter uses - kWh or m³), not a running total -
    and the history doesn't tell us what the absolute meter reading was
    on day one. So we sum the deltas chronologically and then shift the
    whole series so the last point matches the live reading we already
    get from /api/Meters, avoiding a visible jump on the Energy dashboard
    between backfilled history and what HA tracks going forward.

    The *current*, still-in-progress calendar month is deliberately
    excluded from the imported points - ista's row for it is a partial,
    still-changing total (it keeps growing until the month ends), and the
    live polled sensor already builds up that month's real statistics on
    its own as normal state changes come in. Importing a point for it too
    would double up with whatever live tracking computes for the same
    days, and produce inflated/nonsensical numbers once the month actually
    finishes. Its partial value is still used to correct the anchor below,
    just not imported as a statistic point of its own.

    ``active_since``, when given, drops any month before the *current*
    physical meter's own activation date. Water sub-meters in particular
    get physically replaced every few years (calibration requirements) -
    ista's history for a given meter type spans across those
    replacements, but "current_reading" only makes sense relative to the
    meter that's active *now*. Without this filter, a replaced meter's
    older, larger cumulative readings would get anchored to the new
    (near-zero) meter's current reading and produce a nonsensical
    negative/decreasing series for the period before the swap.
    """
    cutoff = (active_since.year, active_since.month) if active_since else None
    now_local = dt_util.now()
    current_period = (now_local.year, now_local.month)

    points: list[tuple[datetime, float]] = []
    current_month_partial = 0.0
    for row in history:
        value = row.get("value")
        raw_date = row.get("date")
        if value is None or raw_date is None:
            continue
        try:
            parsed_raw = datetime.fromisoformat(raw_date)
        except ValueError:
            continue
        period = (parsed_raw.year, parsed_raw.month)
        if cutoff is not None and period < cutoff:
            continue
        if period == current_period:
            current_month_partial += float(value)
            continue
        start = _month_start_utc(raw_date)
        if start is None:
            continue
        points.append((start, float(value)))

    if not points:
        return []

    points.sort(key=lambda p: p[0])

    running = 0.0
    cumulative: list[tuple[datetime, float]] = []
    for start, delta in points:
        running += delta
        cumulative.append((start, running))

    # Anchor the completed-months series to the reading as it stood at the
    # *end of the last completed month* - not today's live reading, which
    # already includes however much has been used so far in the excluded,
    # still-in-progress current month. Subtracting that partial amount
    # avoids inflating every historical month by it.
    anchor_reading = current_reading - current_month_partial
    offset = anchor_reading - cumulative[-1][1]
    result: list[StatisticData] = []
    prev = 0.0
    for start, total in cumulative:
        # Clamp defensively: a physical meter reading can never legitimately
        # go backwards or below zero. With only monthly granularity, the
        # exact month a meter gets physically swapped can carry a small
        # negative/inconsistent blended value (old + new meter mixed in one
        # bucket) - clamping keeps the imported series sane without
        # discarding the rest of that month's data.
        value = round(max(prev, total + offset, 0.0), 3)
        result.append(StatisticData(start=start, sum=value, state=value))
        prev = value
    return result


async def async_backfill_usage_statistics(
    hass: HomeAssistant,
    entity_id: str,
    name: str,
    unit: str,
    history: list[dict[str, Any]],
    current_reading: float,
    active_since: datetime | None = None,
) -> bool:
    """Import ista's monthly usage history as long-term statistics for
    ``entity_id`` (works for the energy meter in kWh or either water meter
    in m³ - ``unit`` must match the live sensor's own unit exactly, or the
    Energy dashboard will refuse to mix them). Returns True if at least
    one point was imported.
    """
    stats = build_statistics(history, current_reading, active_since)
    if not stats:
        _LOGGER.debug("No usable historical data returned by ista for %s", entity_id)
        return False

    metadata = StatisticMetaData(
        has_mean=False,
        has_sum=True,
        name=name,
        source="recorder",
        statistic_id=entity_id,
        unit_of_measurement=unit,
    )
    async_import_statistics(hass, metadata, stats)
    _LOGGER.debug("Imported %d historical statistics points for %s", len(stats), entity_id)
    return True
