import asyncio
from types import SimpleNamespace
from conftest import const, coordinator


class Client:
    host, port, base_url = "example", 8080, "http://example:8080"

    def __init__(self, states):
        self.states = iter(states)

    async def get_playing_status(self):
        return dict(next(self.states))

    async def get_playlists(self):
        return []


def state(schedule=None, playlist="Show"):
    return {
        "status": "playing" if schedule else "idle",
        "scheduleid": schedule or "N/A",
        "schedulename": f"Schedule {schedule}",
        "scheduleend": f"End {schedule}",
        "playlist": playlist if schedule else None,
        "playlistid": "9" if playlist == "Show" else "10",
        "version": "2026.06",
    }


def events_for(states):
    events = []
    hass = SimpleNamespace(
        bus=SimpleNamespace(async_fire=lambda name, data: events.append((name, data)))
    )
    c = coordinator.XScheduleCoordinator(hass, Client(states), {})

    async def update():
        for _ in states:
            await c._async_update_data()

    asyncio.run(update())
    return [
        (name, data)
        for name, data in events
        if name in (const.EVENT_SCHEDULE_STARTED, const.EVENT_SCHEDULE_ENDED)
    ]


def test_adjacent_schedules_end_old_then_start_new_with_old_metadata():
    result = events_for([state("A"), state("B", "Other show")])
    assert [n for n, _ in result] == [
        const.EVENT_SCHEDULE_STARTED,
        const.EVENT_SCHEDULE_ENDED,
        const.EVENT_SCHEDULE_STARTED,
    ]
    ended = result[1][1]
    assert (
        ended["scheduleid"],
        ended["schedulename"],
        ended["scheduleend"],
        ended["playlist"],
    ) == ("A", "Schedule A", "End A", "Show")
    assert result[2][1]["scheduleid"] == "B"


def test_idle_and_repeated_poll_do_not_duplicate_end_events():
    result = events_for([state("A"), state("A"), state(), state()])
    assert [n for n, _ in result] == [
        const.EVENT_SCHEDULE_STARTED,
        const.EVENT_SCHEDULE_ENDED,
    ]


def test_initial_idle_does_not_emit_a_false_end():
    assert events_for([state(), state()]) == []


def test_pausing_a_schedule_does_not_end_it():
    paused = state("A")
    paused["status"] = "paused"
    result = events_for([state("A"), paused, state("A")])
    assert [n for n, _ in result] == [const.EVENT_SCHEDULE_STARTED]


def test_same_step_title_with_different_id_emits_change_and_stable_player_key():
    states = [
        dict(state("A"), step="Song", stepid="1"),
        dict(state("A"), step="Song", stepid="2"),
    ]
    events = []
    hass = SimpleNamespace(
        bus=SimpleNamespace(async_fire=lambda name, data: events.append((name, data)))
    )
    c = coordinator.XScheduleCoordinator(
        hass, Client(states), {}, entry_id="stable-entry"
    )

    async def test():
        for _ in states:
            await c._async_update_data()

    asyncio.run(test())
    changes = [data for name, data in events if name == const.EVENT_STEP_CHANGED]
    assert [data["stepid"] for data in changes] == ["1", "2"]
    assert all(data["config_entry_id"] == "stable-entry" for _, data in events)
    assert all(data["device"] == f"{const.DOMAIN}:stable-entry" for _, data in events)
