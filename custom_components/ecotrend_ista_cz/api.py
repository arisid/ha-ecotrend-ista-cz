"""Lightweight async client for the ista Ecotrend CZ/Nordic backend.

Reverse engineered from a browser HAR capture of https://ecotrend.ista.cz
(a Unity-WebGL app). The relevant REST endpoints live on
``prod.istaonlinebeta.dk`` and use a standard-looking OAuth2
"resource owner password credentials" grant at ``POST /token``.

Known unknown
-------------
The Unity client sends two extra form fields with the login request,
``value1`` (32 bytes) and ``value2`` (48 bytes), each encoded as an
underscore-separated list of integers 0-255, e.g. ``_46_190_76_...``.
Their exact derivation could not be determined from the capture alone
(it happens inside the compiled Unity/IL2CPP WebAssembly binary, which
is not practical to reverse engineer from a HAR file). Because every
other login field is sent in the clear and validated in the plain
"grant_type=password" flow, it is likely these are only used for
device/fraud telemetry on the server side rather than being
cryptographically verified. This client reproduces the same field
*shape* with random bytes. If ista tightens validation and this stops
working, the fix is localised to :meth:`EcotrendIstaCzApiClient._random_value`
and :meth:`_login_payload` below - see the README for how to capture a
fresh HAR to help debug it.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import METERS_URL, TOKEN_EXPIRY_LEEWAY, TOKEN_URL, USERINFO_URL

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = ClientTimeout(total=30)

_COMMON_HEADERS = {
    "Accept": "*/*",
    "Origin": "https://ecotrend.ista.cz",
    "Referer": "https://ecotrend.ista.cz/",
}


class EcotrendIstaCzApiError(Exception):
    """Generic API error."""


class EcotrendIstaCzAuthError(EcotrendIstaCzApiError):
    """Raised when authentication fails (bad credentials or expired session)."""


@dataclass
class EcotrendIstaCzTokens:
    """Holds the current access/refresh token pair."""

    access_token: str
    refresh_token: str | None
    expires_at: float  # monotonic-ish unix timestamp
    user_info: dict[str, Any] = field(default_factory=dict)


class EcotrendIstaCzApiClient:
    """Minimal async client for the ista Ecotrend CZ/Nordic API."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        language: str = "cs-CZ",
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._language = language
        self._tokens: EcotrendIstaCzTokens | None = None

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #

    @staticmethod
    def _random_value(num_bytes: int) -> str:
        """Build an underscore separated byte list like the Unity client sends."""
        rnd = random.SystemRandom()
        return "_" + "_".join(str(rnd.randint(0, 255)) for _ in range(num_bytes))

    def _login_payload(self) -> dict[str, str]:
        return {
            "grant_type": "password",
            "username": self._username,
            "password": self._password,
            "language": self._language,
            "value1": self._random_value(32),
            "value2": self._random_value(48),
        }

    def _refresh_payload(self, refresh_token: str) -> dict[str, str]:
        return {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "language": self._language,
            "value1": self._random_value(32),
            "value2": self._random_value(48),
        }

    async def _post_token(self, payload: dict[str, str]) -> EcotrendIstaCzTokens:
        try:
            resp = await self._session.post(
                TOKEN_URL,
                data=payload,
                headers={
                    **_COMMON_HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=_TIMEOUT,
            )
        except ClientError as err:
            raise EcotrendIstaCzApiError(f"Network error contacting ista: {err}") from err

        if resp.status in (400, 401):
            body = await resp.text()
            _LOGGER.debug("ista token endpoint rejected request: %s %s", resp.status, body)
            raise EcotrendIstaCzAuthError(
                "ista odmítlo přihlašovací údaje (nesprávné jméno/heslo, "
                "nebo se změnil přihlašovací mechanismus - viz README)."
            )
        if resp.status != 200:
            body = await resp.text()
            raise EcotrendIstaCzApiError(f"Unexpected status {resp.status} from ista: {body[:200]}")

        # Note: the raw JSON from ista contains duplicate keys (e.g. two
        # "access_token" / "expires_in" entries). Standard JSON parsing
        # (used by aiohttp/json here) keeps the *last* occurrence of each
        # key, which happens to be the real JWT access token and the
        # correct expiry - matching what the web app itself ends up using.
        data = await resp.json(content_type=None)

        access_token = data.get("access_token")
        if not access_token:
            raise EcotrendIstaCzAuthError("Odpověď ista neobsahovala access_token.")

        try:
            expires_in = int(data.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600

        user_info = {
            k: v
            for k, v in data.items()
            if k
            in (
                "Username",
                "KeycloakUserId",
                "MailValidated",
                "Phone",
                "Email",
                "Language",
                "FirstName",
                "InstanceId",
                "ConsId",
                "isTenant",
                "isAdmin",
            )
        }

        return EcotrendIstaCzTokens(
            access_token=access_token,
            refresh_token=data.get("refresh_token"),
            expires_at=time.time() + expires_in,
            user_info=user_info,
        )

    async def async_login(self) -> EcotrendIstaCzTokens:
        """Perform a full username/password login."""
        self._tokens = await self._post_token(self._login_payload())
        return self._tokens

    async def async_ensure_token(self) -> str:
        """Return a valid access token, logging in / refreshing as needed."""
        if self._tokens is None:
            await self.async_login()
        elif time.time() + TOKEN_EXPIRY_LEEWAY.total_seconds() >= self._tokens.expires_at:
            if self._tokens.refresh_token:
                try:
                    self._tokens = await self._post_token(
                        self._refresh_payload(self._tokens.refresh_token)
                    )
                except EcotrendIstaCzAuthError:
                    _LOGGER.debug("Refresh token rejected, falling back to full login")
                    await self.async_login()
            else:
                await self.async_login()

        assert self._tokens is not None
        return self._tokens.access_token

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {**_COMMON_HEADERS, "Authorization": f"Bearer {token}"}

    async def _get_json(self, url: str) -> Any:
        token = await self.async_ensure_token()
        try:
            resp = await self._session.get(url, headers=self._auth_headers(token), timeout=_TIMEOUT)
        except ClientError as err:
            raise EcotrendIstaCzApiError(f"Network error calling {url}: {err}") from err

        if resp.status == 401:
            # Token might have been invalidated server-side; try one fresh login.
            self._tokens = None
            token = await self.async_ensure_token()
            resp = await self._session.get(url, headers=self._auth_headers(token), timeout=_TIMEOUT)

        if resp.status != 200:
            body = await resp.text()
            raise EcotrendIstaCzApiError(f"Unexpected status {resp.status} from {url}: {body[:200]}")

        return await resp.json(content_type=None)

    # ------------------------------------------------------------------ #
    # Data
    # ------------------------------------------------------------------ #

    async def async_get_user_info(self) -> dict[str, Any]:
        """GET /api/GetUserInfo."""
        return await self._get_json(USERINFO_URL)

    async def async_get_meters(self) -> list[dict[str, Any]]:
        """GET /api/Meters, returns the flattened list of meter dicts."""
        data = await self._get_json(METERS_URL)
        meters = (data or {}).get("Meters", {}).get("Value", [])
        error = (data or {}).get("errorMessage") or {}
        if error.get("UserMessage") or error.get("InternalMessage"):
            _LOGGER.debug("ista Meters endpoint returned an error message: %s", error)
        return meters

    @property
    def user_info(self) -> dict[str, Any]:
        """User profile fields captured from the last successful token response."""
        return self._tokens.user_info if self._tokens else {}
