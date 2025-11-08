from __future__ import annotations

import voluptuous as vol
from typing import Any

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_METER_ID,
    CONF_EAN,
    CONF_API_BASE,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_GRANULARITY,
    CONF_TIME_WINDOW_HOURS,
    DEFAULT_GRANULARITY,
    DEFAULT_TIME_WINDOW_HOURS,
    GRANULARITY_CHOICES,
)

# For obtaining a bearer token via browser automation we reuse the helper from __init__.
from . import _fetch_bearer_token_sync  # type: ignore

from datetime import datetime, timedelta, timezone

# Prepare label lists for the UI: show friendly labels, map back to numeric keys internally.
GRAN_LABELS = list(GRANULARITY_CHOICES.values())
_LABEL_TO_KEY = {v: k for k, v in GRANULARITY_CHOICES.items()}

# Default granularity label
DEFAULT_GRANULARITY_LABEL = GRANULARITY_CHOICES.get(DEFAULT_GRANULARITY, GRAN_LABELS[0])

# Initial setup schema: username & password are required (we persist credentials, not token)
DATA_SCHEMA = vol.Schema(
    {
        vol.Required("name", default="Fluvius Electricity"): str,
        vol.Required(CONF_USERNAME, default=""): str,
        vol.Required(CONF_PASSWORD, default=""): str,
        vol.Required(CONF_EAN, default=""): str,
        vol.Optional(CONF_METER_ID, default=""): str,
        vol.Optional(CONF_API_BASE, default="https://mijn.fluvius.be"): str,
        vol.Optional(CONF_GRANULARITY, default=DEFAULT_GRANULARITY_LABEL): vol.In(GRAN_LABELS),
        vol.Optional(CONF_TIME_WINDOW_HOURS, default=DEFAULT_TIME_WINDOW_HOURS): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
    }
)


async def _validate_token(hass, token: str, ean: str, api_base: str) -> bool:
    """Validate a bearer token by making a small API request.

    Returns True if we get a 200 with parseable JSON.
    """
    if not token or not token.strip():
        return False

    session = async_get_clientsession(hass)
    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=1)

    def fmt(dt: datetime) -> str:
        return dt.astimezone().strftime("%Y-%m-%dT%H:%M:%S.000%z")

    params = {
        "historyFrom": fmt(since),
        "historyUntil": fmt(until),
        "granularity": "1",  # smallest test granularity
        "asServiceProvider": "false",
        "meterSerialNumber": "",
    }

    url = f"{api_base.rstrip('/')}/verbruik/api/meter-measurement-history/{ean or ''}"
    headers = {
        "Authorization": token,
        "Accept": "application/json",
        "User-Agent": "HomeAssistant/Integration",
    }

    try:
        resp = await session.get(url, params=params, headers=headers, timeout=15)
        if resp.status != 200:
            return False
        try:
            await resp.json()
            return True
        except Exception:
            return False
    except Exception:
        return False


class FluviusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow for Fluvius."""

    VERSION = 6

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

        # Read inputs
        username = (user_input.get(CONF_USERNAME) or "").strip()
        password = (user_input.get(CONF_PASSWORD) or "").strip()
        ean = (user_input.get(CONF_EAN) or "").strip()
        api_base = (user_input.get(CONF_API_BASE) or "https://mijn.fluvius.be").strip()
        gran_label = user_input.get(CONF_GRANULARITY)
        time_window = int(user_input.get(CONF_TIME_WINDOW_HOURS, DEFAULT_TIME_WINDOW_HOURS))
        meter_id = (user_input.get(CONF_METER_ID) or "").strip()

        if not ean:
            errors["base"] = "missing_ean"
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

        # Use provided credentials to try to obtain token (in executor) and validate it.
        token = await self.hass.async_add_executor_job(_fetch_bearer_token_sync, username, password)
        if not token:
            errors["base"] = "invalid_credentials_or_2fa"
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

        ok = await _validate_token(self.hass, token, ean, api_base)
        if not ok:
            errors["base"] = "invalid_credentials_or_token"
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

        # Map granularity label back to internal key
        gran_key = _LABEL_TO_KEY.get(gran_label, DEFAULT_GRANULARITY)

        title = user_input.get("name", "Fluvius Electricity")
        # IMPORTANT: we DO NOT persist the bearer token. We persist username/password so the coordinator
        # can re-fetch tokens after restart.
        data = {
            "name": title,
            CONF_USERNAME: username,
            CONF_PASSWORD: password,
            CONF_EAN: ean,
            CONF_METER_ID: meter_id,
            CONF_API_BASE: api_base,
            CONF_GRANULARITY: gran_key,
            CONF_TIME_WINDOW_HOURS: int(time_window),
        }
        return self.async_create_entry(title=title, data=data)

