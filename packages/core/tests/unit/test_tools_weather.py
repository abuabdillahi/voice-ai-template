"""Unit tests for `core.tools.examples.get_weather`.

External HTTP is mocked at the transport layer with
:class:`httpx.MockTransport` so the tests stay deterministic and
fast. The tests assert the externally-observable behaviours called
out in the issue: success, no-results, timeout, and HTTP 500.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from core.tools import examples


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    """Patch :class:`httpx.AsyncClient` to use a :class:`MockTransport`.

    The weather tool constructs its own client, so we replace the
    constructor at the module attribute level for the duration of the
    test. A wrapper subclass is the simplest path that still respects
    the keyword-only ``timeout`` arg the production code passes.
    """
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _ok_response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(payload).encode("utf-8"))


@pytest.mark.asyncio
async def test_successful_path_returns_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding-api" in request.url.host:
            return _ok_response(
                {
                    "results": [
                        {
                            "name": "Berlin",
                            "country": "Germany",
                            "latitude": 52.52,
                            "longitude": 13.41,
                        }
                    ]
                }
            )
        return _ok_response({"current": {"temperature_2m": 18.4, "weather_code": 3}})

    _install_transport(monkeypatch, handler)

    result = await examples.get_weather(city="Berlin")
    assert "Berlin" in result
    assert "Germany" in result
    assert "18.4" in result
    assert "overcast" in result


@pytest.mark.asyncio
async def test_geocode_no_results_returns_graceful_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return _ok_response({"results": []})

    _install_transport(monkeypatch, handler)

    result = await examples.get_weather(city="Atlantis")
    assert "couldn't find" in result.lower()
    assert "Atlantis" in result


@pytest.mark.asyncio
async def test_geocode_timeout_returns_readable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout")

    _install_transport(monkeypatch, handler)

    result = await examples.get_weather(city="Berlin")
    assert "timed out" in result.lower()
    assert "Berlin" in result


@pytest.mark.asyncio
async def test_forecast_500_returns_readable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding-api" in request.url.host:
            return _ok_response(
                {
                    "results": [
                        {
                            "name": "Berlin",
                            "country": "Germany",
                            "latitude": 52.52,
                            "longitude": 13.41,
                        }
                    ]
                }
            )
        return httpx.Response(500, text="boom")

    _install_transport(monkeypatch, handler)

    result = await examples.get_weather(city="Berlin")
    assert "couldn't reach" in result.lower()
    assert "Berlin" in result
