import re

from homeassistant.config_entries import ConfigEntry

DOMAIN = "xlights_scheduler"
INTEGRATION_VERSION = "0.1.0"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_PASSWORD = "password"

CONF_POLL_PLAYING = "poll_interval_playing"
CONF_POLL_IDLE = "poll_interval_idle"
CONF_ENABLE_BROWSE = "enable_browse_media"

DEFAULT_PORT = 8080
DEFAULT_POLL_PLAYING = 2
DEFAULT_POLL_IDLE = 2
DEFAULT_ENABLE_BROWSE = True

PLATFORMS = [
    "media_player",
    "switch",
    "button",
    "select",
    "sensor",
    "number",
]

REFERENCE_PREFIX = "ha:xlights_scheduler"

# Home Assistant event names fired by the integration
EVENT_SCHEDULE_STARTED = f"{DOMAIN}_schedule_started"
EVENT_SCHEDULE_ENDED = f"{DOMAIN}_schedule_ended"
EVENT_PLAYLIST_STARTED = f"{DOMAIN}_playlist_started"
EVENT_PLAYLIST_ENDED = f"{DOMAIN}_playlist_ended"
EVENT_STEP_CHANGED = f"{DOMAIN}_step_changed"
EVENT_OUTPUT_TOGGLED = f"{DOMAIN}_output_toggled"
EVENT_TEST_MODE_STARTED = f"{DOMAIN}_test_mode_started"
EVENT_TEST_MODE_STOPPED = f"{DOMAIN}_test_mode_stopped"
EVENT_PLAYLIST_LOOP_CHANGED = f"{DOMAIN}_playlist_loop_changed"
EVENT_VERSION_CHANGED = f"{DOMAIN}_version_changed"

# How frequently to refresh static lists (playlists/steps) beyond the fast status poll
CONF_LISTS_REFRESH_SECS = "lists_refresh_secs"
DEFAULT_LISTS_REFRESH_SECS = 15


def slugify_entry_title(entry: ConfigEntry) -> str:
    """Return a slug based on the config entry title or host/port.

    Used to build stable, human-readable entity_ids of the form:
    <platform>.xlights_scheduler_<user_given_device_name>_<entity_name>
    """
    name = (entry.title or "").strip()
    if not name:
        host = str(entry.data.get(CONF_HOST, "")).strip()
        port = str(entry.data.get(CONF_PORT, "")).strip()
        name = "_".join(part for part in (host, port) if part)
    if not name:
        name = DOMAIN

    slug = re.sub(r"[^a-z0-9]+", "_", name.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or DOMAIN
