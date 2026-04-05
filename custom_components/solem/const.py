"""Constants for the Solem irrigation integration."""

DOMAIN = "solem"

API_BASE = "https://mysolem.com"
TOKEN_URL = f"{API_BASE}/oauth2/token"
API_URL = f"{API_BASE}/api"

CONF_SESSION_COOKIE = "session_cookie"

# Polling interval (seconds) — LoRa radio polls ~every 2-5 min so 60s is a good balance
DEFAULT_SCAN_INTERVAL = 60

# Watering state values
WATERING_STATE_ON = 0
WATERING_STATE_OFF = 1

# Watering origin values
ORIGIN_SCHEDULED = 0
ORIGIN_MANUAL = 1

# Default manual zone duration (minutes)
DEFAULT_ZONE_DURATION = 10

# Data keys used in coordinator
DATA_MODULES = "modules"
DATA_PROGRAMS = "programs"
DATA_RELAY = "relay"
