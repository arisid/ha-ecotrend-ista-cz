"""Constants for the ista EcoTrend (CZ / Nordic) integration.

This integration talks to the "new" Unity-WebGL based ista Ecotrend portal
used e.g. for https://ecotrend.ista.cz (ista Denmark A/S, Keycloak realm
``eed-nordic``). It is NOT the same backend as the classic ista EcoTrend
app (``api.prod.eed.ista.com`` / realm ``eed-prod``) already supported by
other community integrations - the API below was reverse engineered from a
browser HAR capture of the CZ portal.
"""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "ecotrend_ista_cz"

# --- Endpoints -------------------------------------------------------------
API_BASE = "https://prod.istaonlinebeta.dk"
GRAPHS_BASE = "https://graphs.istaonlinebeta.dk"

TOKEN_URL = f"{API_BASE}/token"
USERINFO_URL = f"{API_BASE}/api/GetUserInfo"
METERS_URL = f"{API_BASE}/api/Meters"
USER_SETTINGS_URL = f"{API_BASE}/api/GetUserSettings"

# "inverval" (not a typo on our end) - that's the actual misspelled query
# param name the real graphs.istaonlinebeta.dk backend expects. Confirmed
# against a real capture that clicked through every UI tab:
#   inverval=1 -> daily, inverval=2 -> weekly,
#   inverval=3 -> monthly, inverval=4 -> yearly
# We use monthly (3) for all three meters - plenty for the Energy
# dashboard's history and far smaller than the daily payload (which was
# ~780KB of JSON for a single meter in the capture).
USAGE_ENERGY_DATA_URL = f"{GRAPHS_BASE}/Overview/Usage_Energy_Data"
USAGE_WATER_HOT_DATA_URL = f"{GRAPHS_BASE}/Overview/Usage_WaterHot_Data"
USAGE_WATER_COLD_DATA_URL = f"{GRAPHS_BASE}/Overview/Usage_WaterCold_Data"
USAGE_HISTORY_INTERVAL_MONTHLY = 3

# --- Config entry keys -------------------------------------------------------
CONF_LANGUAGE = "language"
CONF_ADDRESS = "address"
CONF_CONS_ID = "cons_id"
# List of meter_ids whose historical consumption has already been imported
# into HA long-term statistics, stored on the config entry so we only ever
# do this backfill once per meter (not on every restart/reload).
CONF_HISTORY_IMPORTED = "history_imported_meters"

SERVICE_REIMPORT_HISTORY = "reimport_history"

DEFAULT_LANGUAGE = "cs-CZ"

# --- Update / options --------------------------------------------------------
# ista's own portal only updates meter readings roughly once a week, so
# polling more often than daily just adds needless load on their servers
# for no fresher data. Default to once a day; still configurable via the
# integration's Options if someone wants tighter/looser polling.
DEFAULT_SCAN_INTERVAL = timedelta(days=1)
MIN_SCAN_INTERVAL_MINUTES = 15
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"

# Refresh the token a bit before it actually expires.
TOKEN_EXPIRY_LEEWAY = timedelta(minutes=5)

# Known MeterType values -> (translation key, icon)
METER_TYPE_ICONS = {
    "HW": "mdi:water-thermometer",
    "CW": "mdi:water",
    "ENERGY": "mdi:lightning-bolt",
    "HEAT": "mdi:radiator",
    "ELECTRICITY": "mdi:flash",
}

# API "Unit" string -> HA unit of measurement handled in sensor.py
