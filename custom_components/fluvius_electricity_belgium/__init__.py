from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    DEFAULT_UPDATE_INTERVAL,
    CONF_METER_ID,
    CONF_EAN,
    CONF_API_BASE,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_GRANULARITY,
    CONF_TIME_WINDOW_HOURS,
    DEFAULT_GRANULARITY,
    DEFAULT_TIME_WINDOW_HOURS,
)

_LOGGER = logging.getLogger(__name__)


class FluviusCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch Fluvius data and optionally retrieve token via credentials.

    Important: bearer token is kept only in memory and NOT persisted to the config entry.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        username: str | None,
        password: str | None,
        ean: str | None,
        meter_id: str | None,
        api_base: str | None,
        granularity: str | None,
        time_window_hours: int,
        update_interval: int,
    ):
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} coordinator",
            update_interval=timedelta(seconds=update_interval),
        )
        self.hass = hass
        self.name = name
        # Store credentials (persisted by config entry). Token is cached only in memory.
        self._username = username
        self._password = password
        self._bearer_token: str | None = None  # in-memory cache only
        self.ean = ean
        self.meter_id = meter_id
        self.api_base = (api_base or "https://mijn.fluvius.be").rstrip("/")
        self.granularity = str(granularity or DEFAULT_GRANULARITY)
        self.time_window_hours = int(time_window_hours or DEFAULT_TIME_WINDOW_HOURS)
        self._last_data = None

    def _set_bearer_token(self, token: str | None) -> None:
        """Set the in-memory token cache (not persisted)."""
        self._bearer_token = token

    async def _async_get_bearer_token_if_needed(self) -> str:
        """Ensure we have a bearer token, obtain one using credentials if necessary.

        Token will be cached in memory for this running instance only; it will not be saved
        into the config entry.
        """
        if self._bearer_token:
            return self._bearer_token

        if not self._username or not self._password:
            raise UpdateFailed("No username/password configured to acquire token")

        # Run blocking selenium token fetch in executor
        token = await self.hass.async_add_executor_job(
            _fetch_bearer_token_sync, self._username, self._password
        )
        if not token:
            raise UpdateFailed("Failed to retrieve bearer token using provided credentials")
        # Cache in memory only
        self._set_bearer_token(token)
        return token

    async def _async_update_data(self):
        """
        Fetch data from Fluvius-style API.

        Uses the in-memory bearer token (fetched on demand from credentials).
        """
        session = async_get_clientsession(self.hass)
        try:
            token = await self._async_get_bearer_token_if_needed()

            # Build date range based on configured time_window_hours
            until = datetime.now(timezone.utc)
            since = until - timedelta(hours=self.time_window_hours)

            def fmt(dt: datetime) -> str:
                return dt.astimezone().strftime("%Y-%m-%dT%H:%M:%S.000%z")

            params = {
                "historyFrom": fmt(since),
                "historyUntil": fmt(until),
                "granularity": str(self.granularity),
                "asServiceProvider": "false",
                "meterSerialNumber": self.meter_id or "",
            }

            url = f"{self.api_base}/verbruik/api/meter-measurement-history/{self.ean or ''}"

            headers = {
                "Authorization": token,
                "Accept": "application/json",
                "User-Agent": "HomeAssistant/Integration",
            }

            _LOGGER.debug("Requesting Fluvius data URL=%s params=%s", url, params)
            resp = await session.get(url, params=params, headers=headers, timeout=60)
            text = await resp.text()
            if resp.status != 200:
                if resp.status == 401:
                    _LOGGER.warning("Received 401 from Fluvius; clearing cached token")
                    # Clear in-memory token so next update fetches a new one
                    self._set_bearer_token(None)
                raise UpdateFailed(f"HTTP {resp.status}: {text[:300]}")

            try:
                data = await resp.json()
            except Exception as err:
                raise UpdateFailed(f"Invalid JSON response: {err}") from err

            self._last_data = data
            return data

        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error fetching Fluvius data: {err}") from err


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration from YAML (not used)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change so the new settings take effect."""
    _LOGGER.debug("Fluvius options updated for %s; reloading entry", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fluvius integration from a config entry.

    Note: read configuration from entry.options first (if present) falling back to entry.data.
    """
    def _get(key, default=None):
        return entry.options.get(key, entry.data.get(key, default))

    name = _get("name", entry.title)
    username = _get(CONF_USERNAME)
    password = _get(CONF_PASSWORD)
    ean = _get(CONF_EAN)
    meter_id = _get(CONF_METER_ID)
    api_base = _get(CONF_API_BASE)
    granularity = _get(CONF_GRANULARITY, DEFAULT_GRANULARITY)
    time_window_hours = _get(CONF_TIME_WINDOW_HOURS, DEFAULT_TIME_WINDOW_HOURS)
    update_interval = entry.options.get("update_interval", entry.options.get("update_interval", DEFAULT_UPDATE_INTERVAL))

    coordinator = FluviusCoordinator(
        hass,
        name=name,
        username=username,
        password=password,
        ean=ean,
        meter_id=meter_id,
        api_base=api_base,
        granularity=granularity,
        time_window_hours=time_window_hours,
        update_interval=update_interval,
    )
    # First refresh to validate credentials/token and availability
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Ensure integration reloads when options are updated
    entry.add_update_listener(_async_options_updated)

    hass.config_entries.async_setup_platforms(entry, ["sensor"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


# ---------- Blocking helper using selenium + selenium-wire ----------
def _fetch_bearer_token_sync(username: str, password: str, timeout: int = 60) -> str | None:
    """
    Blocking token fetch using selenium-wire to capture network requests and extract Authorization header.

    NOTE: This runs in an executor from Home Assistant. It requires:
      - selenium and selenium-wire Python packages (listed in manifest requirements)
      - Chrome/Chromium and matching ChromeDriver available on the system PATH
      - 2FA is not supported (the automation expects username/password to reach the logged-in web app)

    The token returned by this helper is intentionally NOT persisted by the integration; it's
    cached in memory only so that the integration can reuse it while the Home Assistant process runs.
    """
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from seleniumwire import webdriver
        import time
    except Exception as exc:
        _LOGGER.exception("Selenium or selenium-wire not available: %s", exc)
        return None

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    seleniumwire_options = {"enable_har": True}

    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options, seleniumwire_options=seleniumwire_options)
        driver.set_page_load_timeout(timeout)
        _LOGGER.info("Authenticating with Fluvius web app to obtain token...")

        driver.get("https://mijn.fluvius.be")
        wait = WebDriverWait(driver, 30)

        try:
            button = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, '//button[@data-testid="b2c-account-type-selection-button-personal"]')
                )
            )
            button.click()
        except Exception:
            pass

        email_input = wait.until(EC.visibility_of_element_located((By.ID, "signInName")))
        email_input.send_keys(username)

        password_input = driver.find_element(By.ID, "password")
        password_input.send_keys(password)

        login_button = driver.find_element(By.ID, "next")
        login_button.click()

        wait.until(lambda d: ("mijn.fluvius.be" in d.current_url) and ("b2clogin" not in d.current_url))

        try:
            cookie_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[@id="fluv-cookies-button-accept-all"]')))
            cookie_button.click()
        except Exception:
            pass

        driver.get("https://mijn.fluvius.be/verbruik")
        time.sleep(5)

        for request in driver.requests:
            try:
                if "/api/" in request.url and request.headers.get("Authorization"):
                    auth_header = request.headers.get("Authorization")
                    if auth_header and auth_header.startswith("Bearer"):
                        _LOGGER.info("Successfully retrieved Bearer token via browser automation")
                        return auth_header
            except Exception:
                continue

        _LOGGER.error("No Bearer token found in captured requests (possible 2FA or changed flow)")
        return None

    except Exception as exc:
        _LOGGER.exception("Exception during token retrieval: %s", exc)
        return None

    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass

