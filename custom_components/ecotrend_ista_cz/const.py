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

# --- Config entry keys -------------------------------------------------------
CONF_LANGUAGE = "language"
CONF_ADDRESS = "address"
CONF_CONS_ID = "cons_id"

DEFAULT_LANGUAGE = "cs-CZ"

# --- Update / options --------------------------------------------------------
DEFAULT_SCAN_INTERVAL = timedelta(minutes=60)
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
