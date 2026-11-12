import asyncio
from urllib.parse import parse_qs, urlsplit
import pytest
from conftest import client


class Response:
    def __init__(self, payload, error=None):
        self.payload, self.error = payload, error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        if self.error:
            raise self.error

    async def json(self, **kwargs):
        return self.payload


class Session:
    def __init__(self, replies):
        self.replies, self.calls = iter(replies), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(next(self.replies))


def run(coroutine):
    return asyncio.run(coroutine)


def parameters(session, index=-1):
    return parse_qs(urlsplit(session.calls[index][0]).query)["Parameters"][0]


@pytest.mark.parametrize("looped", [False, True])
def test_comma_and_pipe_titles_use_current_ids(looped):
    session = Session(
        [
            {"playlists": [{"name": "Show, 2026 | Evening", "id": "7"}]},
            {"steps": [{"name": "Mary, Did You Know | Live", "id": "42"}]},
            {"result": "ok"},
        ]
    )
    instance = client.XScheduleClient(session, "example", 8080, None)
    run(instance.play_step("Show, 2026 | Evening", "Mary, Did You Know | Live", looped))
    assert parameters(session) == "id:7,id:42"
    assert parameters(session, 1) == "id:7"
    assert (
        "looped" in parse_qs(urlsplit(session.calls[-1][0]).query)["Command"][0]
    ) == looped
    assert "+" not in session.calls[-1][0]


def test_explicit_ids_are_accepted_and_steps_still_validated():
    session = Session([{"steps": [{"name": "A", "id": 42}]}, {"result": "ok"}])
    run(
        client.XScheduleClient(session, "example", 8080, None).play_step(
            "id:7", "id:42"
        )
    )
    assert parameters(session) == "id:7,id:42"


@pytest.mark.parametrize(
    "items,value",
    [([], "Missing"), ([{"id": 1, "name": "Same"}, {"id": 2, "name": "Same"}], "Same")],
)
def test_missing_or_duplicate_names_never_send_playback(items, value):
    session = Session([{"playlists": items}])
    with pytest.raises(client.XScheduleError):
        run(
            client.XScheduleClient(session, "example", 8080, None).play_step(
                value, "Song"
            )
        )
    assert len(session.calls) == 1


def test_failed_commands_raise():
    instance = client.XScheduleClient(
        Session([{"result": "failed", "message": "Invalid step"}]),
        "example",
        8080,
        None,
    )
    with pytest.raises(client.XScheduleError, match="Invalid step"):
        run(instance.command("Play playlist step", "id:1,id:2"))


@pytest.mark.parametrize("response", [{}, [], {"result": "ok"}])
def test_bad_status_is_not_reported_as_connected(response):
    instance = client.XScheduleClient(Session([response]), "example", 8080, None)
    with pytest.raises(client.XScheduleError):
        run(instance.get_playing_status())


def test_wrong_password_raises_instead_of_returning_a_status_dict():
    session = Session([{"result": "failed", "ip": "192.0.2.10"}, {"result": "failed"}])
    instance = client.XScheduleClient(session, "example", 8080, "wrong")
    with pytest.raises(client.XScheduleAuthError):
        run(instance.get_playing_status())


def test_authentication_retries_once_then_reports_rejection():
    session = Session(
        [{"result": "not logged in"}, {"result": "ok"}, {"result": "not logged in"}]
    )
    instance = client.XScheduleClient(session, "example", 8080, "secret")
    instance._logged_in = True
    instance._server_seen_ip = "192.0.2.10"
    with pytest.raises(client.XScheduleAuthError):
        run(instance.get_playing_status())
    assert len(session.calls) == 3


def test_successful_reauthentication():
    session = Session(
        [{"result": "not logged in"}, {"result": "ok"}, {"status": "idle"}]
    )
    instance = client.XScheduleClient(session, "example", 8080, "secret")
    instance._logged_in = True
    instance._server_seen_ip = "192.0.2.10"
    assert run(instance.get_playing_status()) == {"status": "idle"}


def test_background_playlist_uses_id_too():
    session = Session(
        [{"playlists": [{"name": "Background, Warm", "id": 8}]}, {"result": "ok"}]
    )
    run(
        client.XScheduleClient(session, "example", 8080, None).set_background(
            "Background, Warm"
        )
    )
    assert parameters(session) == "id:8"
