"""Constants for the GL-iNet integration."""

DOMAIN = "glinet"
DATA_GLINET = "glinet"
API_PATH = "/rpc"
GLINET_FRIENDLY_NAME = "GL-iNet"
GLINET_DEFAULT_URL = "http://192.168.8.1"
GLINET_DEFAULT_PW = "goodlife"
GLINET_DEFAULT_USERNAME = "root"

CONF_TITLE = "title"

# How to handle device trackers for clients using MAC-address randomization.
CONF_TRACK_RANDOMIZED_MAC = "track_randomized_mac"
TRACK_RANDOMIZED_MAC_ENABLED = "enabled"  # track, entity enabled by default
TRACK_RANDOMIZED_MAC_DISABLED = "disabled"  # track, entity disabled by default
TRACK_RANDOMIZED_MAC_IGNORE = "ignore"  # do not create a tracker at all
DEFAULT_TRACK_RANDOMIZED_MAC = TRACK_RANDOMIZED_MAC_DISABLED
