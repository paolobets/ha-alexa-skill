"""Constants for the Alexa Bridge integration."""

DOMAIN = "alexa_bridge"
VIEW_URL = "/api/alexa_bridge/smart_home"

CONF_DOMAINS = "domains"
CONF_INCLUDE_ENTITIES = "include_entities"
CONF_EXCLUDE_ENTITIES = "exclude_entities"
CONF_LOCALE = "locale"
CONF_ENDPOINT = "endpoint"

DEFAULT_LOCALE = "it-IT"
DEFAULT_ENDPOINT = "https://api.eu.amazonalexa.com/v3/events"

# Domains that can never be exposed to Alexa.
BLOCKED_DOMAINS = frozenset({"automation", "alarm_control_panel"})
# binary_sensor device classes shared at domain level.
BINARY_SENSOR_CLASSES = frozenset({"door", "garage_door", "opening", "window", "motion"})
# Entities registered by this platform (Echo devices) are always excluded.
ECHO_PLATFORM = "alexa_media"

STORE_CONFIG = "alexa_bridge"
STORE_AUTH = "alexa_bridge_auth"
STORE_SYNC = "alexa_bridge_sync"

STABLE_ID_PREFIX = "ha-"
