"""Config flow for the ista EcoTrend (CZ / Nordic) integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EcotrendIstaCzApiClient, EcotrendIstaCzApiError, EcotrendIstaCzAuthError
from .const import (
    CONF_ADDRESS,
    CONF_CONS_ID,
    CONF_LANGUAGE,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_LANGUAGE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _validate_and_fetch(hass, username: str, password: str) -> dict[str, Any]:
    """Log in and return details used to build the config entry."""
    session = async_get_clientsession(hass)
    client = EcotrendIstaCzApiClient(session, username, password, language=DEFAULT_LANGUAGE)
    await client.async_login()

    address = ""
    try:
        user_info = await client.async_get_user_info()
        address_parts = [
            str(user_info.get("Address") or "").strip(),
            str(user_info.get("ZipCity") or "").strip(),
        ]
        address = ", ".join(p for p in address_parts if p)
    except EcotrendIstaCzApiError:
        _LOGGER.debug("Could not fetch GetUserInfo for a nicer device name", exc_info=True)

    cons_id = client.user_info.get("ConsId") or username
    return {"cons_id": cons_id, "address": address}


class EcotrendIstaCzConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ista EcoTrend (CZ / Nordic)."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _validate_and_fetch(
                    self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except EcotrendIstaCzAuthError:
                errors["base"] = "invalid_auth"
            except EcotrendIstaCzApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during ista login")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(str(info["cons_id"]))
                self._abort_if_unique_id_configured()

                title = info["address"] or user_input[CONF_USERNAME]
                return self.async_create_entry(
                    title=f"ista EcoTrend - {title}",
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_LANGUAGE: DEFAULT_LANGUAGE,
                        CONF_CONS_ID: info["cons_id"],
                        CONF_ADDRESS: info["address"],
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle re-authentication triggered by ConfigEntryAuthFailed."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None

        if user_input is not None:
            username = self._reauth_entry.data[CONF_USERNAME]
            try:
                await _validate_and_fetch(self.hass, username, user_input[CONF_PASSWORD])
            except EcotrendIstaCzAuthError:
                errors["base"] = "invalid_auth"
            except EcotrendIstaCzApiError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={**self._reauth_entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"username": self._reauth_entry.data[CONF_USERNAME]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> "EcotrendIstaCzOptionsFlow":
        return EcotrendIstaCzOptionsFlow(entry)


class EcotrendIstaCzOptionsFlow(OptionsFlow):
    """Options: how often to poll ista for new readings."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self._entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES, int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL_MINUTES, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL_MINUTES)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
