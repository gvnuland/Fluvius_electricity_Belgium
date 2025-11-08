"""Constants for the Fluvius Electricity Belgium integration."""

DOMAIN = "fluvius_electricity_belgium"
PLATFORMS = ["sensor"]

DEFAULT_NAME = "Fluvius Electricity"
DEFAULT_UPDATE_INTERVAL = 300  # seconds (5 minutes)

CONF_METER_ID = "meter_id"
CONF_EAN = "ean"
CONF_BEARER_TOKEN = "bearer_token"
CONF_API_BASE = "api_base"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_GRANULARITY = "granularity"
CONF_TIME_WINDOW_HOURS = "time_window_hours"

# Defaults
DEFAULT_GRANULARITY = "1"  # '1' = 15 minutes by convention used in examples
DEFAULT_TIME_WINDOW_HOURS = 24  # last 24 hours

# Friendly granularity choices displayed to user (keys are sent to API)
GRANULARITY_CHOICES = {
    "1": "15 minutes",
    "2": "30 minutes",
    "3": "Daily (per day)",
}
