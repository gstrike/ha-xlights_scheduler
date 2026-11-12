"""Load the client/coordinator without starting a Home Assistant instance.

Minimal HA boundary stubs keep these protocol/state tests fast. Deployed code
is additionally loaded and validated against the user's actual HA version.
"""

import datetime
import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_review_xlights_scheduler"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_components/xlights_scheduler")]
sys.modules[PACKAGE] = package


def module(name, **attributes):
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    sys.modules[name] = result
    return result


class HomeAssistantError(Exception):
    pass


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass, self.update_interval = hass, update_interval


module("homeassistant")
module("homeassistant.config_entries", ConfigEntry=object)
module(
    "homeassistant.exceptions",
    HomeAssistantError=HomeAssistantError,
    ConfigEntryAuthFailed=type("ConfigEntryAuthFailed", (HomeAssistantError,), {}),
)
module("homeassistant.core", HomeAssistant=object)
module("homeassistant.helpers")
module(
    "homeassistant.helpers.update_coordinator",
    DataUpdateCoordinator=DataUpdateCoordinator,
    UpdateFailed=UpdateFailed,
)
utildt = module(
    "homeassistant.util.dt",
    utcnow=lambda: datetime.datetime.now(datetime.timezone.utc),
    parse_datetime=lambda value: datetime.datetime.fromisoformat(value),
    as_utc=lambda value: value.astimezone(datetime.timezone.utc),
)
module("homeassistant.util", dt=utildt)


def load(name):
    full = PACKAGE + "." + name
    spec = importlib.util.spec_from_file_location(
        full, ROOT / "custom_components/xlights_scheduler" / f"{name}.py"
    )
    result = importlib.util.module_from_spec(spec)
    sys.modules[full] = result
    spec.loader.exec_module(result)
    return result


const = load("const")
client = load("client")
coordinator = load("coordinator")
module(
    "homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None
)
integration = load("__init__")

# Entity/flow boundaries for playback, availability, identity and form tests.
from enum import IntFlag


class Entity:
    def async_write_ha_state(self):
        pass


class CoordinatorEntity:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success


class Features(IntFlag):
    PLAY = 1
    PAUSE = 2
    STOP = 4
    TURN_ON = 8
    TURN_OFF = 16
    VOLUME_SET = 32
    VOLUME_MUTE = 64
    SEEK = 128
    BROWSE_MEDIA = 256
    PLAY_MEDIA = 512
    SELECT_SOURCE = 1024


class BrowseMedia:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


module("homeassistant.components")
module(
    "homeassistant.components.media_player",
    BrowseMedia=BrowseMedia,
    MediaClass=types.SimpleNamespace(DIRECTORY="directory", MUSIC="music"),
    MediaPlayerEntity=Entity,
    MediaPlayerEntityFeature=Features,
)
module("homeassistant.components.select", SelectEntity=Entity)
module("homeassistant.components.switch", SwitchEntity=Entity)
module(
    "homeassistant.components.sensor",
    SensorEntity=Entity,
    SensorDeviceClass=types.SimpleNamespace(),
)
module(
    "homeassistant.helpers.entity",
    EntityCategory=types.SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic"),
)
module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
sys.modules[
    "homeassistant.helpers.update_coordinator"
].CoordinatorEntity = CoordinatorEntity
sys.modules["homeassistant.exceptions"].ConfigEntryAuthFailed = type(
    "ConfigEntryAuthFailed", (HomeAssistantError,), {}
)
sys.modules["homeassistant.core"].callback = lambda f: f


class Flow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    def async_update_reload_and_abort(self, entry, **kwargs):
        return {"type": "abort", "entry": entry, **kwargs}

    def _async_current_entries(self):
        return getattr(self, "entries", [])

    async def async_set_unique_id(self, value):
        self.unique_id = value

    def _abort_if_unique_id_configured(self):
        pass


sys.modules["homeassistant.config_entries"].ConfigFlow = Flow
sys.modules["homeassistant.config_entries"].OptionsFlow = Flow
sys.modules["homeassistant.config_entries"].OptionsFlowWithReload = Flow
module("homeassistant.data_entry_flow", FlowResult=dict)
media_player = load("media_player")
select = load("select")
switch = load("switch")
sensor = load("sensor")
config_flow = load("config_flow")
