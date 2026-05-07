"""Unit tests for :mod:`core.clinician`.

The :class:`httpx.AsyncClient` is patched at the module boundary —
no live Nominatim or Overpass call is made. Every failure-taxonomy
row is exercised; the radius fallback ladder is walked end-to-end.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from core import clinician
from core.config import Settings


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "supabase_url": "https://test.supabase.co",
        "supabase_publishable_key": "test-publishable",
        "supabase_jwks_url": "https://test.supabase.co/auth/v1/.well-known/jwks.json",
        "livekit_url": "wss://test.livekit.cloud",
        "livekit_api_key": "lk-test-key",  # pragma: allowlist secret
        "livekit_api_secret": "lk-test-secret",  # pragma: allowlist secret
        "openai_api_key": "sk-test-openai",  # pragma: allowlist secret
        "osm_contact_email": "ops@example.com",
        "nominatim_base_url": "https://nominatim.example.com",
        "overpass_base_url": "https://overpass.example.com/api",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Empty cache and disable the rate-limit and failover sleeps."""
    clinician._clear_cache_for_tests()
    # The 1 req/sec policy isn't observable in unit tests; stub the
    # interval to zero so the suite stays quick.
    monkeypatch.setattr(clinician, "_NOMINATIM_RATE_LIMIT_INTERVAL_SECONDS", 0.0)
    # Same idea for the inter-mirror backoff: tests assert the failover
    # contract, not the wall-clock pacing.
    monkeypatch.setattr(clinician, "_OVERPASS_RETRY_BACKOFF_SECONDS", 0.0)
    yield
    clinician._clear_cache_for_tests()


# --- Mock transport helper --------------------------------------------------

# A simple recording handler — the test parametrises a per-request
# response factory and we capture every outgoing request for later
# assertions.


class _Transport:
    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self._handler = handler
        self.requests: list[httpx.Request] = []

    def to_mock(self) -> httpx.MockTransport:
        async def _async(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._handler(request)

        return httpx.MockTransport(_async)


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, transport: _Transport) -> None:
    """Force every :class:`httpx.AsyncClient` to use our mock transport."""
    real_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport.to_mock()
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)


def _nominatim_hit(
    *,
    display_name: str = "Brooklyn, Kings County, New York, United States",
    lat: str = "40.6501",
    lon: str = "-73.9496",
) -> httpx.Response:
    return httpx.Response(
        200,
        json=[{"display_name": display_name, "lat": lat, "lon": lon}],
    )


def _nominatim_empty() -> httpx.Response:
    return httpx.Response(200, json=[])


def _overpass_payload(elements: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, json={"elements": elements})


def _make_node(
    *,
    osm_id: int,
    name: str,
    lat: float,
    lon: float,
    tags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = {"name": name, "healthcare": "physiotherapist"}
    if tags:
        base.update(tags)
    return {"type": "node", "id": osm_id, "lat": lat, "lon": lon, "tags": base}


# --- Happy path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_five_results_at_10km(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = [
        _make_node(
            osm_id=1,
            name="Park PT",
            lat=40.6510,
            lon=-73.9500,
            tags={
                "phone": "555-1234",
                "addr:housenumber": "10",
                "addr:street": "Main St",
                "addr:city": "Brooklyn",
                "addr:postcode": "11215",
            },
        ),
        _make_node(osm_id=2, name="Bay Wellness", lat=40.6520, lon=-73.9505),
        _make_node(osm_id=3, name="Atlantic Rehab", lat=40.6530, lon=-73.9520),
        _make_node(
            osm_id=4,
            name="Greenpoint OT",
            lat=40.6550,
            lon=-73.9560,
            tags={"healthcare": "occupational_therapist"},
        ),
        _make_node(osm_id=5, name="Downtown Movement", lat=40.6600, lon=-73.9600),
        _make_node(osm_id=6, name="Faraway PT", lat=41.0, lon=-74.5),
    ]

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return _nominatim_hit()
        return _overpass_payload(nodes)

    transport = _Transport(_handler)
    _patch_async_client(monkeypatch, transport)

    raw = await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    payload = json.loads(raw)

    assert "error" not in payload
    assert payload["specialist_label"] == "physiotherapist or occupational therapist"
    assert payload["location_resolved"] == "Brooklyn, Kings County, New York, United States"
    assert payload["radius_km"] == 10
    assert payload["count"] == 5
    assert len(payload["results"]) == 5
    # Sorted ascending by distance.
    distances = [r["distance_km"] for r in payload["results"]]
    assert distances == sorted(distances)
    first = payload["results"][0]
    assert first["name"] == "Park PT"
    assert first["url"] == "https://www.openstreetmap.org/node/1"
    assert first["phone"] == "555-1234"
    assert "Main St" in first["address"]
    assert isinstance(first["distance_km"], float)


# --- Nominatim parsing ------------------------------------------------------


@pytest.mark.asyncio
async def test_nominatim_top_hit_selected_and_lat_lon_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return httpx.Response(
                200,
                json=[
                    {"display_name": "First Hit", "lat": "12.5", "lon": "-1.25"},
                    {"display_name": "Second Hit", "lat": "0", "lon": "0"},
                ],
            )
        # Capture overpass query body for the lat/lon assertion.
        captured["body"] = request.content.decode("utf-8")
        return _overpass_payload(
            [
                _make_node(osm_id=1, name="Clinic", lat=12.50, lon=-1.25),
            ]
        )

    _patch_async_client(monkeypatch, _Transport(_handler))

    raw = await clinician.find_clinics("upper_trapezius_strain", "Anywhere", settings=_settings())
    payload = json.loads(raw)

    assert payload["location_resolved"] == "First Hit"
    assert "12.5" in captured["body"]
    assert "-1.25" in captured["body"]


# --- Overpass query construction --------------------------------------------


@pytest.mark.asyncio
async def test_overpass_query_unions_each_specialist_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return _nominatim_hit()
        captured.append(request.content.decode("utf-8"))
        return _overpass_payload(
            [
                _make_node(osm_id=1, name="One", lat=40.65, lon=-73.95),
            ]
        )

    _patch_async_client(monkeypatch, _Transport(_handler))

    await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    body = captured[0]
    # Both filter halves rendered, all three element kinds queried.
    assert '"healthcare"="physiotherapist"' in body
    assert '"healthcare"="occupational_therapist"' in body
    for kind in ("node", "way", "relation"):
        assert f"{kind}[" in body
    # 10 km == 10000 m for the first ladder rung.
    assert "around:10000," in body


@pytest.mark.asyncio
async def test_overpass_radius_changes_per_ladder_rung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """10 km empty → 25 km empty → 50 km has results; radius_km is 50."""
    rung = {"i": 0}
    captured_radii: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return _nominatim_hit()
        body = request.content.decode("utf-8")
        captured_radii.append(body)
        rung["i"] += 1
        if rung["i"] < 3:
            return _overpass_payload([])
        return _overpass_payload(
            [
                _make_node(osm_id=1, name="Faraway PT", lat=40.7, lon=-73.95),
            ]
        )

    _patch_async_client(monkeypatch, _Transport(_handler))

    raw = await clinician.find_clinics("lumbar_strain", "Brooklyn", settings=_settings())
    payload = json.loads(raw)

    assert payload["radius_km"] == 50
    assert payload["count"] == 1
    assert "around:10000," in captured_radii[0]
    assert "around:25000," in captured_radii[1]
    assert "around:50000," in captured_radii[2]


# --- Result dedup -----------------------------------------------------------


@pytest.mark.asyncio
async def test_result_dedup_collapses_repeat_node_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A node tagged with multiple matching filters appears once."""
    nodes = [
        _make_node(osm_id=42, name="Dual Tag PT", lat=40.65, lon=-73.95),
        _make_node(
            osm_id=42,
            name="Dual Tag PT",
            lat=40.65,
            lon=-73.95,
            tags={"healthcare": "occupational_therapist"},
        ),
    ]

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return _nominatim_hit()
        return _overpass_payload(nodes)

    _patch_async_client(monkeypatch, _Transport(_handler))

    raw = await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    payload = json.loads(raw)

    assert payload["count"] == 1
    assert payload["results"][0]["url"] == "https://www.openstreetmap.org/node/42"


# --- Distance ---------------------------------------------------------------


def test_haversine_km_matches_known_pair() -> None:
    """Brooklyn → Manhattan ~8.4 km via standard haversine.

    Hand-calculated against the great-circle formula; the function
    must round-trip to within 0.1 km of the manual fixture.
    """
    distance = clinician._haversine_km(40.6501, -73.9496, 40.7128, -74.0060)
    assert abs(distance - 8.44) < 0.1


# --- LRU cache --------------------------------------------------------------


@pytest.mark.asyncio
async def test_nominatim_cache_hit_skips_second_http_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nominatim_calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            nominatim_calls["n"] += 1
            return _nominatim_hit()
        return _overpass_payload(
            [
                _make_node(osm_id=1, name="One", lat=40.65, lon=-73.95),
            ]
        )

    _patch_async_client(monkeypatch, _Transport(_handler))

    await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    # Second call's locality lookup is served from cache.
    assert nominatim_calls["n"] == 1


@pytest.mark.asyncio
async def test_cache_key_lowercases_and_trims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nominatim_calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            nominatim_calls["n"] += 1
            return _nominatim_hit()
        return _overpass_payload(
            [
                _make_node(osm_id=1, name="One", lat=40.65, lon=-73.95),
            ]
        )

    _patch_async_client(monkeypatch, _Transport(_handler))

    await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    await clinician.find_clinics("carpal_tunnel", "  brooklyn  ", settings=_settings())
    assert nominatim_calls["n"] == 1


# --- Failure-taxonomy rows --------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_condition_returns_taxonomy_row_one() -> None:
    raw = await clinician.find_clinics("made_up_condition", "Brooklyn", settings=_settings())
    assert json.loads(raw) == {
        "error": (
            "I don't have a referral path for that condition. Let me know "
            "what you've been experiencing and we can take it from the top."
        )
    }


@pytest.mark.asyncio
async def test_empty_location_returns_taxonomy_row_two() -> None:
    raw = await clinician.find_clinics("carpal_tunnel", "   ", settings=_settings())
    assert json.loads(raw) == {
        "error": ("I didn't catch a location — could you tell me what city or " "area you're in?")
    }


@pytest.mark.asyncio
async def test_missing_contact_email_returns_network_unavailable() -> None:
    settings = _settings(osm_contact_email=None)
    raw = await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=settings)
    payload = json.loads(raw)
    assert "error" in payload
    assert "couldn't reach the maps service" in payload["error"]
    assert "physiotherapist or occupational therapist" in payload["error"]


@pytest.mark.asyncio
async def test_nominatim_zero_results_returns_taxonomy_row_four(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return _nominatim_empty()
        return _overpass_payload([])

    _patch_async_client(monkeypatch, _Transport(_handler))

    raw = await clinician.find_clinics("carpal_tunnel", "NotARealPlace", settings=_settings())
    payload = json.loads(raw)
    assert "error" in payload
    assert "NotARealPlace" in payload["error"]
    assert "town name or postcode" in payload["error"]


@pytest.mark.asyncio
async def test_overpass_zero_after_full_ladder_returns_taxonomy_row_six(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return _nominatim_hit()
        return _overpass_payload([])

    _patch_async_client(monkeypatch, _Transport(_handler))

    raw = await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    payload = json.loads(raw)
    assert "error" in payload
    assert "50 km" in payload["error"]
    assert "physiotherapist or occupational therapist" in payload["error"]
    assert "Google Maps" in payload["error"]


@pytest.mark.asyncio
async def test_network_error_returns_taxonomy_row_seven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    _patch_async_client(monkeypatch, _Transport(_handler))

    raw = await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    payload = json.loads(raw)
    assert "error" in payload
    assert "couldn't reach the maps service" in payload["error"]


@pytest.mark.asyncio
async def test_overpass_5xx_returns_network_error_when_every_mirror_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user-visible error string only fires once both the primary
    Overpass URL and every fallback mirror have raised — single-mirror
    flapping must not leak through.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return _nominatim_hit()
        return httpx.Response(503, json={"error": "service unavailable"})

    transport = _Transport(_handler)
    _patch_async_client(monkeypatch, transport)

    raw = await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    payload = json.loads(raw)
    assert "couldn't reach the maps service" in payload["error"]

    overpass_hosts = {
        request.url.host
        for request in transport.requests
        if request.url.host != "nominatim.example.com"
    }
    # Primary plus every fallback URL must have been attempted.
    expected_hosts = {"overpass.example.com"} | {
        httpx.URL(url).host for url in clinician._OVERPASS_FALLBACK_MIRRORS
    }
    assert overpass_hosts == expected_hosts


@pytest.mark.asyncio
async def test_overpass_failure_falls_over_to_mirror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the primary Overpass URL 5xx's, the next mirror in the
    failover list is tried, and a successful response from the mirror
    is returned to the caller.
    """
    monkeypatch.setattr(
        clinician,
        "_OVERPASS_FALLBACK_MIRRORS",
        ("https://mirror.example.com/api",),
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.example.com":
            return _nominatim_hit()
        if request.url.host == "overpass.example.com":
            return httpx.Response(504, text="gateway timeout")
        # Mirror succeeds.
        return _overpass_payload(
            [
                _make_node(osm_id=1, name="Mirror PT", lat=40.65, lon=-73.95),
            ]
        )

    transport = _Transport(_handler)
    _patch_async_client(monkeypatch, transport)

    raw = await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    payload = json.loads(raw)

    assert "error" not in payload
    assert payload["count"] == 1
    assert payload["results"][0]["name"] == "Mirror PT"
    overpass_hosts = [
        request.url.host
        for request in transport.requests
        if request.url.host != "nominatim.example.com"
    ]
    # Primary tried first, then mirror — single rung, no extra calls.
    assert overpass_hosts == ["overpass.example.com", "mirror.example.com"]


# --- User-Agent -------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_agent_header_carries_version_and_contact_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        ua = request.headers.get("user-agent", "")
        assert "voice-ai-ergo-triage/" in ua
        assert "ops@example.com" in ua
        if request.url.host == "nominatim.example.com":
            return _nominatim_hit()
        return _overpass_payload(
            [
                _make_node(osm_id=1, name="One", lat=40.65, lon=-73.95),
            ]
        )

    _patch_async_client(monkeypatch, _Transport(_handler))

    raw = await clinician.find_clinics("carpal_tunnel", "Brooklyn", settings=_settings())
    assert "error" not in json.loads(raw)
