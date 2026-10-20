"""Config flow for Solem irrigation integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from yarl import URL

from homeassistant import config_entries
from homeassistant.const import CONF_TOKEN
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import SolemAPI, SolemAuthError, SolemAPIError
from .const import API_BASE, CONF_SESSION_COOKIE, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_SCHEMA = vol.Schema({
    vol.Required(CONF_TOKEN): TextSelector(
        TextSelectorConfig(type=TextSelectorType.PASSWORD)
    ),
    vol.Required(CONF_SESSION_COOKIE): TextSelector(
        TextSelectorConfig(type=TextSelectorType.PASSWORD)
    ),
})


async def _async_validate(token: str, cookie: str) -> dict[str, Any]:
    """Validate the token/cookie pair and return the LRMB10 relay module.

    Raises SolemAuthError, SolemAPIError or LookupError (no relay in account).
    """
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        api = SolemAPI(session)
        api._token = token
        session.cookie_jar.update_cookies(
            {"solem-irrigation-platform.sid": cookie},
            response_url=URL(API_BASE),
        )
        data = await api.get_user_with_modules()
    relay = next(
        (m for m in data.get("modules", []) if m.get("type") == "lr-mb-10"),
        None,
    )
    if relay is None:
        raise LookupError("no relay")
    return relay


class SolemConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Setup: paste Bearer token + session cookie from Proxyman."""

    VERSION = 1

    async def _async_check(
        self, user_input: dict[str, Any], errors: dict[str, str]
    ) -> dict[str, Any] | None:
        """Validate user input, fill errors and return the relay on success."""
        try:
            return await _async_validate(
                user_input[CONF_TOKEN].strip(),
                user_input[CONF_SESSION_COOKIE].strip(),
            )
        except SolemAuthError:
            errors["base"] = "invalid_auth"
        except SolemAPIError:
            errors["base"] = "cannot_connect"
        except LookupError:
            errors["base"] = "no_relay_found"
        except Exception:
            _LOGGER.exception("Unexpected error during Solem setup")
            errors["base"] = "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            relay = await self._async_check(user_input, errors)
            if relay is not None:
                await self.async_set_unique_id(relay["id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=relay.get("name", "Solem"),
                    data={
                        CONF_TOKEN: user_input[CONF_TOKEN].strip(),
                        CONF_SESSION_COOKIE: user_input[CONF_SESSION_COOKIE].strip(),
                        "relay_id": relay["id"],
                        "relay_serial": relay.get("serialNumber"),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Triggered by ConfigEntryAuthFailed when the token has expired."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask for a new token + cookie and store them."""
        return await self._async_update_credentials(
            "reauth_confirm", self._get_reauth_entry(), user_input
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Let the user replace the token + cookie at any time."""
        return await self._async_update_credentials(
            "reconfigure", self._get_reconfigure_entry(), user_input
        )

    async def _async_update_credentials(
        self,
        step_id: str,
        entry: config_entries.ConfigEntry,
        user_input: dict[str, Any] | None,
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            relay = await self._async_check(user_input, errors)
            if relay is not None:
                await self.async_set_unique_id(relay["id"])
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_TOKEN: user_input[CONF_TOKEN].strip(),
                        CONF_SESSION_COOKIE: user_input[CONF_SESSION_COOKIE].strip(),
                    },
                )

        return self.async_show_form(
            step_id=step_id,
            data_schema=STEP_SCHEMA,
            errors=errors,
        )
