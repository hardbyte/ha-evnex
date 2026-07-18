"""Constants for evnex charger integration."""

from homeassistant.const import Platform

# Base component constants
NAME = "evnex"
DOMAIN = "evnex"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.9.0b1"
ATTRIBUTION = "Data provided by https://evnex.io"
ISSUE_URL = "https://github.com/hardbyte/ha-evnex/issues"

# Platforms
PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.BUTTON]

# Configuration and options
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

TOKEN_FILE_NAME = "evnex_session.json"

# Token keys stored in config entry data
CONF_ID_TOKEN = "id_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCESS_TOKEN = "access_token"

CONF_MFA_CODE = "mfa_code"

# Coordinator Data Keys

# Signals
DATA_UPDATED = "evnex_data_updated"

CHARGER_SESSION_READY_STATES = ["SUSPENDED_EVSE", "CHARGING"]
