# xSchedule (xLights Scheduler) - Home Assistant Custom Integration

Control and monitor xSchedule (aka xLights Scheduler, part of xLights) from Home Assistant. This integration exposes a media player, core controls, selectors, services, and events so you can automate playback, volume, loop options, output-to-lights, and more.

- Media player: shows current playlist/step with progress; play/pause/stop, seek, set volume/mute
- Switches: output-to-lights, playlist loop, test mode
- Selects: playlist, step, and background playlist
- Buttons: next, prior, restart step, stop all now
  - Plus: close xSchedule (shuts down the app)
- Sensors: playlist/step, next schedule, song/show time remaining, playback source, xSchedule version
- Media Browser: browse Playlists -> Steps and play from there
- Events: fires when a schedule starts/ends

> This is a custom integration. Place this folder at `config/custom_components/xlights_scheduler` in your HA config.

Open this repository in HACS, then confirm the download:

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gstrike&repository=ha-xlights_scheduler&category=integration)

## Installation

1. Copy the `xlights_scheduler` folder into your Home Assistant config:
   - `<your-ha-config>/custom_components/xlights_scheduler`
2. Restart Home Assistant.
3. In HA, go to Settings > Devices & Services > Add Integration > "xLights Scheduler".
4. Enter:
   - Host/IP of the xSchedule machine
   - Port (default 8080) - match xSchedule Options > Web Server Port
   - Password (optional; leave blank if xSchedule has no password)

## Features

### Entities

- Media Player (`media_player.xlights_scheduler_*`)
  - State: playing / paused / idle
  - Title: `[Playlist]:  [Step]`
  - Features: Play, Pause, Stop, Seek, Volume Set/Mute, Select Source (playlist), Browse Media, Play Media

- Switches
  - `switch.xlights_scheduler_output_to_lights` - toggle output to lights
  - `switch.xlights_scheduler_playlist_loop` - toggle loop for current playlist
  - `switch.xlights_scheduler_test_mode` - start/stop test mode

- Number
  - `number.xlights_scheduler_brightness` - set global brightness 0-100%

- Selects
  - `select.xlights_scheduler_playlist` - choose a playlist, then press Play
  - `select.xlights_scheduler_step` - select + play a step in the active/selected playlist
  - `select.xlights_scheduler_background_playlist` - set or clear background playlist

- Buttons
  - `button.xlights_scheduler_next_step`
  - `button.xlights_scheduler_prior_step`
  - `button.xlights_scheduler_restart_step`
  - `button.xlights_scheduler_stop_all_now`

- Sensors
  - Playlist step count, current playlist and current step
  - Next scheduled start, minutes until start, and next scheduled playlist
  - Song time remaining and show time remaining (seconds)
  - Playback source (manual / scheduled / queued / idle)
  - xSchedule version

Entity IDs include a device-specific name between the integration prefix and
entity suffix; use HA's entity picker to select your actual entity.

### Services (domain: `xlights_scheduler`)

- `play_playlist(playlist, looped)`
- `stop_playlist()`
- `play_step(playlist, step, looped)`
- `seek_ms(position_ms)`
- `toggle_playlist_loop()` / `set_playlist_loop(state)`
- `toggle_output_to_lights()` / `set_output_to_lights(state)`
- `set_volume(volume)` / `adjust_volume(delta)`
- Test mode: `start_test_mode(mode?, model?, interval?, foreground?, background?)` and `stop_test_mode()`

### Events

- `xlights_scheduler_schedule_started`
  - Data: `scheduleid`, `schedulename`, `playlistid`, `playlist`, `scheduleend`
- `xlights_scheduler_schedule_ended`
  - Data: `scheduleid`
- `xlights_scheduler_playlist_started`
  - Data: `playlist`, `playlistid`, `status`, `trigger`, `device`
- `xlights_scheduler_playlist_ended`
  - Data: `playlist`, `playlistid`, `status`, `device`
- `xlights_scheduler_step_changed`
  - Data: `playlist`, `playlistid`, `step`, `stepid`, `previous_step`, `status`, `device`
- `xlights_scheduler_output_toggled`
  - Data: `state`, `playlist`, `playlistid`, `status`, `device`
- `xlights_scheduler_playlist_loop_changed`
  - Data: `loop`, `playlist`, `playlistid`, `status`, `device`
- `xlights_scheduler_test_mode_started`
  - Data: `mode`, `device`
- `xlights_scheduler_test_mode_stopped`
  - Data: `device`
- `xlights_scheduler_version_changed`
  - Data: `version`, `device`

Use 'Event' triggers in automations to respond to schedule changes.

### Media Browser

Browse 'Playlists' to choose a playlist and then its steps; play directly from the tree. Works with standard `media_player.play_media` commands.

## Options

Settings > Devices & Services > xLights Scheduler > Configure

- Poll interval (playing/paused) - default 2s
- Poll interval (idle) - default 2s
- Enable Browse Media - default on
- Refresh playlists/steps every (seconds) - default 15s
  - Playlists refresh on first run and then on this cadence. Step lists refresh on demand and when the playlist changes (short TTL).
  - Playlists also refresh immediately when xSchedule's reported `version` changes (e.g., after an upgrade).

## Development testing alongside HACS

Build the isolated test integration from the regular source:

```sh
python3 scripts/build_package.py --dev
```

Copy `dist/custom_components/xlights_scheduler_dev` into HA's
`config/custom_components/`, check HA's configuration, and restart HA Core.
Then add **xLights Scheduler Dev** through Settings > Devices & Services.
Use the same xSchedule host, port and password as the regular integration.
This creates separate entities, `xlights_scheduler_dev` actions and
`xlights_scheduler_dev_*` events. Existing automations keep using the regular
integration unless explicitly changed. Both integrations control the same
player, so avoid issuing conflicting commands from test automations.

Test playback of a step containing commas via the Dev `play_step` action,
selectors and media browser. An invalid step should report an error without
starting anything. Check that consecutive schedules emit the previous
schedule's ended event before the new schedule's started event.

Install test tools with `python -m pip install -r requirements-dev.txt`, then
run `pytest -q` (Python 3.12+).
These use small Home Assistant boundary stubs; validate setup and playback
on the actual HA instance as well.

For a future HACS release, `python3 scripts/build_package.py` builds the regular
`dist/xlights_scheduler.zip`; validate it with
`python3 scripts/validate_package.py`. Publishing that archive with a matching version
tag is a separate step. Installing Dev does not replace the HACS files or
change the installed regular version. Remove Dev after validating the real
HACS notification and upgrade.

## Playback information and connection changes

The song/show remaining sensors expose xSchedule's `leftms` and
`playlistleftms` values in seconds, including fractional seconds. Show remaining
is the server's remaining playlist traversal; it is not a prediction of the end
of an indefinitely looping show. Missing timing values remain unknown. Playback
source is `manual`, `scheduled`, `queued`, or `idle`.

Every emitted event includes `config_entry_id`, `host`, `port`, `base_url`, and
`device` (`<integration-domain>:<config-entry-id>`). The device value now remains
stable across reloads. Automations filtering the previous temporary object-based
value should switch to `config_entry_id` or the new stable device value.

Custom actions accept an optional `config_entry_id` player selector. When more
than one player is loaded, selecting a player is required. Entity controls
already target their own player. Play and Pause are idempotent; use an explicit
play-step or play-playlist action to deliberately restart/change playback.
Playlist looping is available only while a playlist is active, because the
server cannot preconfigure it while idle.

Use the integration's Reconfigure menu to change host, port or password.
Connection/authentication is checked before saving; entity/device registry IDs
are preserved. Options changes reload the entry automatically. Intervals must
be positive whole seconds, and disabling Browse Media removes browsing support.

The upstream API does not report background-playlist or test-mode status.
These controls explicitly use assumed state, shared between local actions and
entities. Changes made directly in xSchedule cannot be discovered through its
current status endpoint. List refresh failures appear in the media player's
`list_refresh_error` attribute and HA logs while the previous list is retained.

## HA Dev acceptance checklist

Use **xLights Scheduler Dev**, not the HACS integration, for these checks:

1. Start a song from its media browser. Confirm **Song time remaining**,
   **Show time remaining**, and **Playback source** appear; source is `manual`.
   Pause: timing should stop decreasing. Stop: timing becomes unknown and source
   becomes `idle`. During a scheduled show, source should become `scheduled`.
2. Press Play twice during a song: playback must not restart. Press Pause twice:
   it must stay paused. Press Play to resume without restarting.
3. Under Configure, set idle polling to 5 seconds and disable Browse Media.
   After the automatic reload, browsing should disappear. Re-enable it and
   restore the interval. Zero/negative intervals must be rejected.
4. Under Reconfigure, try an unused port: saving must fail and leave the current
   connection intact. Save the valid host/port/password again and confirm existing
   entity IDs remain intact. If an alternate hostname for the same VM is
   available, changing to it and back should also preserve those IDs.
5. In Developer Tools > Events, listen for
   `xlights_scheduler_dev_step_changed` and
   `xlights_scheduler_dev_schedule_started`/`schedule_ended`. Check stable
   `config_entry_id` across an integration reload. At a schedule change, the old
   ended event must precede the new started event. Polling can miss transitions
   shorter than the polling interval.
6. When convenient, run the Dev start/stop test-mode actions and confirm the Dev
   test-mode switch follows. Background selection should show the requested
   choice and support Clear background. These remain assumed states.
7. If testing multiple players, select the intended Player in each Dev action.
   Omitting it with multiple loaded players must report an error. When a player
   is offline, its controls should become unavailable after the next failed poll.

## Author

- Greg Strike (https://github.com/gstrike/)

## Acknowledgements

- xLights developers and community
- Home Assistant developers and community

## Translations

Initial translations (es, fr, de) were generated with the help of AI and may contain mistakes or awkward phrasing. Pull requests to improve existing locales or add new languages are very welcome.

## License

MIT License. See the `LICENSE` file for details.
