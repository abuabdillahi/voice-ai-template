"""Example tools shipped in the template.

These two tools serve as the canonical pattern downstream developers
copy when adding their own. They demonstrate:

* the ``@tool`` decorator (no boilerplate beyond a docstring + type
  hints),
* async + ``httpx.AsyncClient`` with an explicit timeout,
* multi-step API calls (geocode → forecast),
* graceful failure when the upstream returns nothing useful or a
  transport error occurs,
* the system-prompt seam: tools must be announced in the agent's
  instructions so the model knows it can call them (see
  :mod:`agent.session`).

The implementations are intentionally simple. A production project
would add caching, retries, and richer parsing — those are downstream
concerns; the template's job is to make the *pattern* obvious.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from core.tools.registry import tool

# Open-Meteo offers free, key-less geocoding and forecast endpoints.
# The two-step pattern (resolve a place name → query weather by
# lat/lon) is the standard shape any "external lookup" tool ends up in,
# so we deliberately exercise it here.
_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# 5 seconds is a sane upper bound for a voice tool: a turn that takes
# longer than this feels broken to the user, and the model can
# verbalise the timeout while we move on.
_HTTP_TIMEOUT = 5.0


@tool
async def get_current_time(timezone: str = "UTC") -> str:
    """Return the current time in the requested IANA timezone.

    The default is UTC. Pass an IANA name like ``Europe/Berlin`` or
    ``America/Los_Angeles``. Invalid names are reported as a readable
    error string rather than raising, so the agent can apologise
    verbally.
    """
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return f"I don't recognise the timezone {timezone!r}."

    now = datetime.now(tz=zone)
    return f"The current time in {timezone} is {now.isoformat(timespec='seconds')}."


@tool
async def get_weather(city: str) -> str:
    """Look up the current weather in a city using Open-Meteo.

    Performs two HTTP calls — first a geocoding lookup to resolve the
    city to coordinates, then a forecast call to fetch the current
    temperature and weather code — and returns a short natural-
    language summary. Returns a graceful message when the city cannot
    be resolved or the upstream request fails.
    """
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            geo_resp = await client.get(
                _GEOCODING_URL,
                params={"name": city, "count": 1},
            )
            geo_resp.raise_for_status()
            geo_payload: dict[str, Any] = geo_resp.json()
            results = geo_payload.get("results") or []
            if not results:
                return f"I couldn't find a place called {city}."
            place = results[0]
            lat = place["latitude"]
            lon = place["longitude"]
            display_name = place.get("name", city)
            country = place.get("country")

            forecast_resp = await client.get(
                _FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weather_code",
                },
            )
            forecast_resp.raise_for_status()
            forecast_payload: dict[str, Any] = forecast_resp.json()
            current = forecast_payload.get("current") or {}
            temp = current.get("temperature_2m")
            code = current.get("weather_code")
    except httpx.TimeoutException:
        return f"The weather service timed out while looking up {city}."
    except httpx.HTTPError as exc:
        return f"I couldn't reach the weather service for {city}: {exc}."

    if temp is None:
        return f"I couldn't read the current weather for {display_name}."

    summary = _describe_weather_code(code) if code is not None else "current"
    location = f"{display_name}, {country}" if country else display_name
    return f"In {location} it is currently {temp}°C with {summary} conditions."


# WMO weather interpretation codes — Open-Meteo's documented mapping.
# We keep the table small and group codes into broad buckets so the
# spoken summary stays natural ("light rain" rather than "weather code
# 51").
_WEATHER_CODE_DESCRIPTIONS: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "light rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "light snow",
    73: "moderate snow",
    75: "heavy snow",
    80: "rain showers",
    81: "rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}


def _describe_weather_code(code: int) -> str:
    """Map a WMO weather code to a short human description."""
    return _WEATHER_CODE_DESCRIPTIONS.get(code, "unknown")


__all__ = ["get_current_time", "get_weather"]
