"""Config flow for Solem irrigation integration."""
from __future__ import annotations

import logging
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


class SolemConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Setup: paste Bearer token + session cookie from Proxyman."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            cookie = user_input[CONF_SESSION_COOKIE].strip()

            session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
            api = SolemAPI(session)
            api._token = token
            session.cookie_jar.update_cookies(
                {"solem-irrigation-platform.sid": cookie},
                response_url=URL(API_BASE),
            )
            try:
                data = await api.get_user_with_modules()
                relay = next(
                    (m for m in data.get("modules", []) if m.get("type") == "lr-mb-10"),
                    None,
                )
                if relay is None:
                    errors["base"] = "no_relay_found"
                else:
                    await self.async_set_unique_id(relay["id"])
                    self._abort_if_unique_id_configured()
                    await session.close()
                    return self.async_create_entry(
                        title=relay.get("name", "Solem"),
                        data={
                            CONF_TOKEN: token,
                            CONF_SESSION_COOKIE: cookie,
                            "relay_id": relay["id"],
                            "relay_serial": relay.get("serialNumber"),
                        },
                    )
            except SolemAuthError:
                errors["base"] = "invalid_auth"
            except SolemAPIError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Solem setup")
                errors["base"] = "unknown"
            finally:
                if not session.closed:
                    await session.close()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )
