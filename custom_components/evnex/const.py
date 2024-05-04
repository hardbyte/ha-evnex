"""Constants for evnex charger integration."""

from homeassistant.const import Platform

# Base component constants
NAME = "evnex"
DOMAIN = "evnex"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.6.0a2"
ATTRIBUTION = "Data provided by https://evnex.io"
ISSUE_URL = "https://github.com/hardbyte/ha-evnex/issues"

# Platforms
PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]

# Configuration and options
CONF_ENABLED = "enabled"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

TOKEN_FILE_NAME = "evnex_session.json"

# Internal
DATA_CLIENT = "evnex-client"
DATA_COORDINATOR = "coordinator"

# Coordinator Data Keys

# Signals
DATA_UPDATED = "evnex_data_updated"
