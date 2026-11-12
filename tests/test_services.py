import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from conftest import integration, const, client


def services(error=None):
    handlers = {}
    connection = SimpleNamespace(
        play_step=AsyncMock(side_effect=error), control_lock=asyncio.Lock()
    )
    coordinator = SimpleNamespace(async_request_refresh=AsyncMock())
    hass = SimpleNamespace(
        data={
            const.DOMAIN: {"entry": {"client": connection, "coordinator": coordinator}}
        },
        services=SimpleNamespace(
            async_register=lambda domain, name, handler, **kwargs: handlers.update(
                {name: handler}
            )
        ),
    )
    integration._register_services(hass)
    return handlers, connection, coordinator


def test_ha_receives_coroutine_service_handlers_and_awaits_step_playback():
    handlers, connection, coordinator = services()
    assert all(inspect.iscoroutinefunction(h) for h in handlers.values())
    asyncio.run(
        handlers["play_step"](
            SimpleNamespace(
                service="play_step",
                data={
                    "playlist": "Show, 2026",
                    "step": "Mary, Did You Know",
                    "looped": False,
                },
            )
        )
    )
    connection.play_step.assert_awaited_once_with(
        "Show, 2026", "Mary, Did You Know", looped=False
    )
    coordinator.async_request_refresh.assert_awaited_once()


def test_rejected_playback_propagates_instead_of_refreshing_as_success():
    handlers, connection, coordinator = services(client.XScheduleError("Invalid step"))
    with pytest.raises(client.XScheduleError, match="Invalid step"):
        asyncio.run(
            handlers["play_step"](
                SimpleNamespace(
                    service="play_step", data={"playlist": "Show", "step": "Missing"}
                )
            )
        )
    coordinator.async_request_refresh.assert_not_awaited()
