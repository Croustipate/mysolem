"""Solem irrigation integration for Home Assistant."""
from __future__ import annotations

import logging

import aiohttp
from yarl import URL

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant

from .api import SolemAPI, SolemAPIError
from .const import API_BASE, CONF_SESSION_COOKIE, DOMAIN
from .coordinator import SolemCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SWITCH, Platform.SENSOR, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Solem from a config entry."""
    # Dedicated session — unsafe=True so manually injected cookies are accepted
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    api = SolemAPI(session)

    # Inject stored token
    api._token = entry.data[CONF_TOKEN]

    # Inject session cookie required for /manual/ endpoint
    cookie = entry.data.get(CONF_SESSION_COOKIE, "")
    if cookie:
        session.cookie_jar.update_cookies(
            {"solem-irrigation-platform.sid": cookie},
            response_url=URL(API_BASE),
        )
    else:
        _LOGGER.warning("Solem: no session cookie — /manual/ commands may fail")

    # relay_serial: try stored value, fall back to fetching from API
    relay_serial = entry.data.get("relay_serial")
    if not relay_serial:
        try:
            data = await api.get_user_with_modules()
            relay = next(
                (m for m in data.get("modules", []) if m.get("type") == "lr-mb-10"),
                None,
            )
            relay_serial = relay.get("serialNumber") if relay else ""
        except SolemAPIError as err:
            _LOGGER.error("Solem: could not fetch relay serial: %s", err)
            relay_serial = ""

    coordinator = SolemCoordinator(
        hass, api,
        relay_id=entry.data["relay_id"],
        relay_serial=relay_serial,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        await session.close()
        raise

    outputs = coordinator.data.get("outputs", [])
    programs = coordinator.data.get("programs", [])
    _LOGGER.info(
        "Solem: loaded %d zones and %d programs", len(outputs), len(programs)
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: SolemCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.api._session.close()
    return unloaded
