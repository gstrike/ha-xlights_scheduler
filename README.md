# xSchedule (xLights Scheduler) - Home Assistant Custom Integration

Control and monitor xSchedule (aka xLights Scheduler, part of xLights) from Home Assistant. This integration exposes a media player, core controls, selectors, services, and events so you can automate playback, volume, loop options, output-to-lights, and more.

- Media player: shows current playlist/step with progress; play/pause/stop, seek, set volume/mute
- Switches: output-to-lights, playlist loop, test mode
- Selects: playlist, step, and background playlist
- Buttons: next, prior, restart step, stop all now
  - Plus: close xSchedule (shuts down the app)
- Sensors: playlist step count, current playlist step, next scheduled start
- Media Browser: browse Playlists -> Steps and play from there
- Events: fires when a schedule starts/ends

> This is a custom integration. Place this folder at `config/custom_components/xlights_scheduler` in your HA config.

Or easily install using this handy dandy button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gstrike&repository=https%3A%2F%2Fgithub.com%2Fgstrike%2Fha-xlights_scheduler&category=integration)

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
  - `select.xlights_scheduler_playlist` - select + play a playlist
  - `select.xlights_scheduler_step` - select + play a step in the active/selected playlist
  - `select.xlights_scheduler_background_playlist` - set or clear background playlist

- Buttons
  - `button.xlights_scheduler_next_step`
  - `button.xlights_scheduler_prior_step`
  - `button.xlights_scheduler_restart_step`
  - `button.xlights_scheduler_stop_all_now`

- Sensors
  - `sensor.xlights_scheduler_queue_length`
  - `sensor.xlights_scheduler_next_scheduled_start`

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
  - Data: `scheduleid`, `schedulename`, `playlistid`, `playlist`, `scheduleend`, `trigger`
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
  - Playlists also refresh immediately when xSchedule's reported `version` changes (e.g., after restart/upgrade).

## Author

- Greg Strike (https://github.com/gstrike/)

## Acknowledgements

- xLights developers and community
- Home Assistant developers and community

## Translations

Initial translations (es, fr, de) were generated with the help of AI and may contain mistakes or awkward phrasing. Pull requests to improve existing locales or add new languages are very welcome.

## License

MIT License. See the `LICENSE` file for details.
