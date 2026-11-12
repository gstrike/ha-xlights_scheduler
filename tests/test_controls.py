import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from conftest import (
    const,
    client,
    integration,
    media_player,
    select,
    switch,
    sensor,
    config_flow,
)


def entry(host="example", port=8080, unique_id="example:8080", options=None):
    return NS(
        data={"host": host, "port": port, "password": ""},
        unique_id=unique_id,
        title="xSchedule",
        entry_id="stable-entry",
        options=options or {},
    )


def objects(status="playing", options=None):
    coordinator = NS(
        data={
            "status": status,
            "playlist": "Show",
            "step": "Song",
            "playlistlooping": "false",
        },
        last_update_success=True,
        async_request_refresh=AsyncMock(),
        test_mode=None,
        background_playlist=None,
        event_context={"config_entry_id": "stable-entry"},
    )
    connection = NS(
        control_lock=asyncio.Lock(),
        get_playing_status=AsyncMock(side_effect=lambda: dict(coordinator.data)),
        pause_toggle=AsyncMock(),
        play_step=AsyncMock(),
        play_playlist=AsyncMock(),
        command=AsyncMock(return_value={"result": "ok"}),
        set_background=AsyncMock(),
    )
    obj = media_player.XScheduleMediaPlayer(
        connection, coordinator, entry(options=options)
    )
    obj.hass = NS(data={const.DOMAIN: {"stable-entry": {}}})
    return obj, connection, coordinator


def test_play_while_playing_does_not_restart_even_with_stored_selection():
    obj, c, _ = objects()
    obj.hass.data[const.DOMAIN]["stable-entry"].update(
        selected_playlist="Old selection", selected_step="Song"
    )
    asyncio.run(obj.async_media_play())
    c.play_step.assert_not_awaited()
    c.play_playlist.assert_not_awaited()
    c.pause_toggle.assert_not_awaited()


def test_pause_is_idempotent_and_respects_fresh_status():
    obj, c, co = objects()

    async def toggle():
        co.data["status"] = "paused"

    c.pause_toggle.side_effect = toggle

    async def test():
        await obj.async_media_pause()
        await obj.async_media_pause()

    asyncio.run(test())
    c.pause_toggle.assert_awaited_once()


def test_play_resumes_once_then_subsequent_play_is_noop():
    obj, c, co = objects("paused")

    async def toggle():
        co.data["status"] = "playing"

    c.pause_toggle.side_effect = toggle

    async def test():
        await obj.async_media_play()
        await obj.async_media_play()

    asyncio.run(test())
    c.pause_toggle.assert_awaited_once()


def test_disabled_browsing_removes_feature_and_rejects_browse():
    obj, _, _ = objects(options={const.CONF_ENABLE_BROWSE: False})
    assert (
        not obj.supported_features & media_player.MediaPlayerEntityFeature.BROWSE_MEDIA
    )
    with pytest.raises(client.XScheduleError.__bases__[0], match="disabled"):
        asyncio.run(obj.async_browse_media())


def test_step_and_loop_controls_unavailable_when_disconnected():
    _, c, co = objects()
    co.last_update_success = False
    hass = NS(data={const.DOMAIN: {"stable-entry": {"selected_playlist": "Show"}}})
    assert not select.StepSelect(hass, c, co, entry()).available
    assert not switch.PlaylistLoopSwitch(c, co, entry()).available
    co.last_update_success = True
    co.data["status"] = "idle"
    assert not switch.PlaylistLoopSwitch(c, co, entry()).available


def test_reconfiguration_preserves_existing_entity_and_device_identity():
    obj, c, co = objects()
    moved = media_player.XScheduleMediaPlayer(c, co, entry("new.example", 8090))
    assert moved._attr_unique_id == obj._attr_unique_id
    assert moved.device_info["identifiers"] == obj.device_info["identifiers"]


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("leftms", "12345", 12.345),
        ("playlistleftms", "50000", 50),
        ("leftms", "-20", 0),
        ("leftms", None, None),
        ("leftms", "bad", None),
        ("trigger", "manual", "manual"),
        ("trigger", "scheduled", "scheduled"),
        ("trigger", "queued", "queued"),
    ],
)
def test_playback_info_uses_server_values(field, value, expected):
    _, c, co = objects()
    co.data[field] = value
    obj = sensor.PlaybackInfoSensor(c, co, entry(), "test", field)
    assert obj.native_value == expected
    co.data["status"] = "idle"
    assert obj.native_value == ("idle" if field == "trigger" else None)


def test_multiple_players_require_target_and_route_explicit_entry():
    one = NS(client="one", coordinator="first")
    two = NS(client="two", coordinator="second")
    hass = NS(data={const.DOMAIN: {"a": vars(one), "b": vars(two)}})
    with pytest.raises(client.XScheduleError.__bases__[0], match="config_entry_id"):
        integration._get_integration_objects(hass)
    assert integration._get_integration_objects(hass, "b") == ("two", "second")
    with pytest.raises(client.XScheduleError.__bases__[0], match="not loaded"):
        integration._get_integration_objects(hass, "missing")


def test_background_selection_marks_state_as_assumed_and_tracks_clear():
    _, c, co = objects()
    obj = select.BackgroundPlaylistSelect(NS(), c, co, entry())

    async def test():
        await obj.async_select_option("Background, Warm")
        assert obj.current_option == "Background, Warm"
        await obj.async_select_option("Clear background")
        assert obj.current_option == "Clear background"

    asyncio.run(test())
    assert obj.assumed_state


def test_test_mode_actions_and_switch_share_the_same_state():
    _, c, co = objects()
    handlers = {}
    events = []
    hass = NS(
        data={const.DOMAIN: {"stable-entry": {"client": c, "coordinator": co}}},
        services=NS(
            async_register=lambda domain, name, handler, **kwargs: handlers.update(
                {name: handler}
            )
        ),
        bus=NS(async_fire=lambda *args: events.append(args)),
    )
    integration._register_services(hass)
    obj = switch.TestModeSwitch(c, co, entry())
    assert obj.is_on is None

    async def test():
        await handlers["start_test_mode"](NS(service="start_test_mode", data={}))
        assert obj.is_on is True
        await handlers["stop_test_mode"](NS(service="stop_test_mode", data={}))
        assert obj.is_on is False

    asyncio.run(test())
    assert events[0][1]["config_entry_id"] == "stable-entry"


@pytest.mark.parametrize(
    "values",
    [
        {const.CONF_POLL_IDLE: 0},
        {const.CONF_POLL_PLAYING: -1},
        {const.CONF_LISTS_REFRESH_SECS: 0},
    ],
)
def test_options_reject_nonpositive_intervals(values):
    flow = config_flow.XScheduleOptionsFlow()
    flow.config_entry = entry()
    result = asyncio.run(flow.async_step_init(values))
    assert result["errors"] == {"base": "invalid_interval"}


def test_options_accept_positive_values_and_use_ha_auto_reload_class():
    flow = config_flow.XScheduleOptionsFlow()
    flow.config_entry = entry()
    result = asyncio.run(flow.async_step_init({const.CONF_POLL_IDLE: 5}))
    assert (
        result["type"] == "create_entry" and result["data"][const.CONF_POLL_IDLE] == 5
    )
    assert (
        config_flow.XScheduleOptionsFlow.__bases__[0]
        is config_flow.config_entries.OptionsFlowWithReload
    )


def test_reconfigure_validates_updates_existing_entry_and_preserves_unique_id():
    flow = config_flow.XScheduleConfigFlow()
    current = entry()
    flow._get_reconfigure_entry = lambda: current
    flow._validate_connection = AsyncMock(
        return_value={"host": "new.example", "port": 8090, "password": "updated"}
    )
    result = asyncio.run(
        flow.async_step_reconfigure({"host": "new.example", "port": 8090})
    )
    assert result["entry"] is current
    assert result["data_updates"]["host"] == "new.example"
    assert result["unique_id"] == "new.example:8090"
    assert result["data_updates"]["_player_key"] == "example:8080"
    updated = entry("new.example", 8090, unique_id=result["unique_id"])
    updated.data.update(result["data_updates"])
    assert const.player_key(updated) == const.player_key(current)


def test_failed_reconfigure_does_not_update_connection():
    flow = config_flow.XScheduleConfigFlow()
    current = entry()
    flow._get_reconfigure_entry = lambda: current
    flow._validate_connection = AsyncMock(
        side_effect=client.XScheduleAuthError("wrong password")
    )
    result = asyncio.run(
        flow.async_step_reconfigure({"host": "new.example", "port": 8090})
    )
    assert result["type"] == "form" and result["errors"] == {"base": "invalid_auth"}
    assert current.data["host"] == "example"


def test_duplicate_reconfigure_address_is_rejected():
    flow = config_flow.XScheduleConfigFlow()
    current = entry()
    other = entry("other", 8090)
    other.entry_id = "other"
    flow._get_reconfigure_entry = lambda: current
    flow.entries = [current, other]
    flow._validate_connection = AsyncMock(return_value={"host": "other", "port": 8090})
    result = asyncio.run(flow.async_step_reconfigure({"host": "other", "port": 8090}))
    assert result["reason"] == "already_configured"


def test_refresh_requests_do_not_overlap_and_publish_choices_after_completion():
    async def test():
        _, c, co = objects()
        gate = asyncio.Event()
        tasks = []

        async def get_steps(playlist):
            await gate.wait()
            return [{"name": "Song", "id": "1"}]

        c.get_steps = AsyncMock(side_effect=get_steps)
        config = entry()

        def create_task(hass, target, name):
            task = asyncio.create_task(target)
            tasks.append(task)
            return task

        config.async_create_background_task = create_task
        hass = NS(data={const.DOMAIN: {"stable-entry": {"selected_playlist": "Show"}}})
        obj = select.StepSelect(hass, c, co, config)
        obj._handle_coordinator_update()
        obj._handle_coordinator_update()
        await asyncio.sleep(0)
        assert len(tasks) == 1 and c.get_steps.await_count == 1
        gate.set()
        await tasks[0]
        assert obj.options == ["Song"]

    asyncio.run(test())


def test_service_schemas_reject_missing_fields_and_invalid_values():
    import voluptuous as vol

    schemas = {}
    hass = NS(
        services=NS(
            async_register=lambda domain, name, handler, **kwargs: schemas.update(
                {name: kwargs["schema"]}
            )
        )
    )
    integration._register_services(hass)
    for action, data in [
        ("play_step", {"playlist": "All"}),
        ("set_volume", {"volume": 101}),
        ("seek_ms", {"position_ms": -1}),
    ]:
        with pytest.raises(vol.Invalid):
            schemas[action](data)
    assert (
        schemas["play_step"](
            {"playlist": "All", "step": "Song, Live", "config_entry_id": "player"}
        )["looped"]
        is False
    )


def test_play_uses_fresh_server_status_when_ha_refresh_is_debounced():
    obj, connection, co = objects("playing")
    connection.get_playing_status.side_effect = None
    connection.get_playing_status.return_value = dict(co.data, status="paused")
    asyncio.run(obj.async_media_play())
    connection.pause_toggle.assert_awaited_once()


def test_repeated_set_output_does_not_toggle_back_when_ha_cache_is_stale():
    _, connection, co = objects()
    co.data["outputtolights"] = "true"
    remote = dict(co.data)
    connection.get_playing_status.side_effect = lambda: dict(remote)

    async def toggle():
        remote["outputtolights"] = (
            "false" if remote["outputtolights"] == "true" else "true"
        )

    connection.toggle_output_to_lights = AsyncMock(side_effect=toggle)
    handlers = {}
    hass = NS(
        data={const.DOMAIN: {"player": {"client": connection, "coordinator": co}}},
        services=NS(
            async_register=lambda domain, name, handler, **kwargs: handlers.update(
                {name: handler}
            )
        ),
    )
    integration._register_services(hass)

    async def test():
        for _ in range(2):
            await handlers["set_output_to_lights"](
                NS(service="set_output_to_lights", data={"state": False})
            )

    asyncio.run(test())
    connection.toggle_output_to_lights.assert_awaited_once()
    assert remote["outputtolights"] == "false"
