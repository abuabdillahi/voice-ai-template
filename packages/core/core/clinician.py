"""Nominatim + Overpass plumbing for the find-clinician feature.

Pure-functional deep module — every interaction with OpenStreetMap
lives behind one async entrypoint, :func:`find_clinics`. The agent
worker calls it through a thin tool wrapper (``core.tools.triage
.find_clinician``); no other module in the codebase references the
upstream wire shapes or the radius-fallback ladder.

Failure-mode design — every path returns a verbalisable JSON-encoded
string. Exceptions never escape :func:`find_clinics`; the realtime
model paraphrases the ``error`` field rather than crashing the voice
loop. Sparse OSM coverage is handled as a first-class case via the
10 km → 25 km → 50 km → graceful fallback radius ladder rather than as
an exception. Overpass HTTP failures (504/429/timeouts on the public
instance under load) trigger a per-rung mirror failover before
escalating to the network-error string — see
``_OVERPASS_FALLBACK_MIRRORS``.

OSMF usage policy obligations honoured here:

* a ``User-Agent`` header naming the project version and a contact
  email (sourced from :class:`Settings.osm_contact_email`) on every
  Nominatim and Overpass request;
* an in-process semaphore plus per-acquire delay enforcing 1 req/sec
  against the public Nominatim instance;
* a 256-entry, 24-hour LRU cache for Nominatim responses keyed on the
  lower-cased trimmed locality string so repeat lookups within a
  session never re-pound the public service.

Configuration:

* ``OSM_CONTACT_EMAIL`` — required; absence disables the feature
  cleanly (network-unavailable string returned, structured warning
  logged at startup by :class:`Settings` consumers).
* ``NOMINATIM_BASE_URL`` — defaults to the public instance.
* ``OVERPASS_BASE_URL`` — defaults to the public interpreter.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from importlib import metadata as _metadata
from typing import Any

import httpx
import structlog

from core.conditions import CONDITIONS
from core.config import Settings

_log = structlog.get_logger("core.clinician")


# --- Tunables ---------------------------------------------------------------

_NOMINATIM_TIMEOUT_SECONDS = 5.0
_OVERPASS_TIMEOUT_SECONDS = 8.0
_TOTAL_BUDGET_SECONDS = 12.0

_RADIUS_LADDER_KM: tuple[int, ...] = (10, 25, 50)
_TOP_RESULTS = 5

_NOMINATIM_CACHE_MAX_ENTRIES = 256
_NOMINATIM_CACHE_TTL_SECONDS = 24 * 60 * 60

# OSMF Nominatim usage policy: <= 1 request / second from any single
# source. Implemented via a process-local semaphore plus a per-acquire
# delay so two concurrent triage sessions cannot collude into a 2 rps
# burst against the public instance.
_NOMINATIM_RATE_LIMIT_INTERVAL_SECONDS = 1.0

# Overpass failover. The primary URL comes from
# ``settings.overpass_base_url`` and the public OSMF instance is the
# default — it routinely 429s and 504s under load. ``kumi.systems`` is
# an independently-operated public mirror with separate rate limits, so
# stepping through it on a primary failure breaks the otherwise
# correlated outage. Each mirror is tried with a short backoff in
# between; only when every mirror fails does the call escalate to the
# user-visible network-error string. The radius ladder still drives
# the outer loop — failover is per-rung, not per-overall-call.
_OVERPASS_FALLBACK_MIRRORS: tuple[str, ...] = ("https://overpass.kumi.systems/api/interpreter",)
_OVERPASS_RETRY_BACKOFF_SECONDS = 1.0


# --- User-Agent -------------------------------------------------------------


def _package_version() -> str:
    """Return the installed ``core`` package version, or ``"0.0.0"``."""
    try:
        return _metadata.version("core")
    except _metadata.PackageNotFoundError:  # pragma: no cover — editable install
        return "0.0.0"


def _user_agent(contact_email: str) -> str:
    return f"voice-ai-ergo-triage/{_package_version()} ({contact_email})"


# --- Failure-taxonomy strings ----------------------------------------------
# One source of truth for the verbatim wording the realtime model
# paraphrases. Each is wrapped in a `{"error": ...}` payload by the
# helpers below so the wire shape on the success and failure paths is
# discriminable by JSON-key presence.

_ERR_UNKNOWN_CONDITION = (
    "I don't have a referral path for that condition. Let me know what "
    "you've been experiencing and we can take it from the top."
)
_ERR_EMPTY_LOCATION = (
    "I didn't catch a location — could you tell me what city or area " "you're in?"
)


def _err_zero_geocode(user_string: str) -> str:
    return (
        f"I couldn't find a place called {user_string} on the map — "
        "could you give me a town name or postcode?"
    )


def _err_zero_results(specialist_label: str, resolved_locality: str) -> str:
    return (
        f"I couldn't find any {specialist_label} tagged in OpenStreetMap "
        f"within 50 km of {resolved_locality}. Your best bet is to "
        f"search Google Maps for '{specialist_label} near "
        f"{resolved_locality}' directly."
    )


def _err_network(specialist_label: str, user_string: str) -> str:
    return (
        f"I couldn't reach the maps service just now. Try Google Maps "
        f"for '{specialist_label} near {user_string}' instead."
    )


def _error_payload(message: str) -> str:
    return json.dumps({"error": message})


# --- Nominatim cache + rate-limit ------------------------------------------


class _NominatimEntry:
    __slots__ = ("expires_at", "value")

    def __init__(self, value: dict[str, Any], expires_at: float) -> None:
        self.value = value
        self.expires_at = expires_at


# Module-level state: one cache + one semaphore per process.
_NOMINATIM_CACHE: dict[str, _NominatimEntry] = {}
_NOMINATIM_LOCK: asyncio.Lock | None = None
_NOMINATIM_LAST_CALL_AT: float = 0.0


def _get_nominatim_lock() -> asyncio.Lock:
    """Return the process-local semaphore, creating it on first use.

    ``asyncio.Lock`` must be instantiated inside a running event loop
    or it binds to whichever loop happened to be current at import
    time — fragile for tests that build their own loop.
    """
    global _NOMINATIM_LOCK
    if _NOMINATIM_LOCK is None:
        _NOMINATIM_LOCK = asyncio.Lock()
    return _NOMINATIM_LOCK


def _cache_key(location: str) -> str:
    return location.strip().lower()


def _cache_get(key: str) -> dict[str, Any] | None:
    entry = _NOMINATIM_CACHE.get(key)
    if entry is None:
        return None
    if entry.expires_at < time.monotonic():
        _NOMINATIM_CACHE.pop(key, None)
        return None
    return entry.value


def _cache_put(key: str, value: dict[str, Any]) -> None:
    if len(_NOMINATIM_CACHE) >= _NOMINATIM_CACHE_MAX_ENTRIES:
        # FIFO eviction is fine for a 256-entry cache; locality
        # strings have low cardinality per session and the TTL keeps
        # the hit rate honest.
        first_key = next(iter(_NOMINATIM_CACHE))
        _NOMINATIM_CACHE.pop(first_key, None)
    _NOMINATIM_CACHE[key] = _NominatimEntry(
        value=value,
        expires_at=time.monotonic() + _NOMINATIM_CACHE_TTL_SECONDS,
    )


def _clear_cache_for_tests() -> None:
    """Reset the Nominatim cache between tests."""
    global _NOMINATIM_LAST_CALL_AT
    _NOMINATIM_CACHE.clear()
    _NOMINATIM_LAST_CALL_AT = 0.0


# --- Geocode (Nominatim) ---------------------------------------------------


async def _geocode(
    location: str,
    *,
    settings: Settings,
    client: httpx.AsyncClient,
) -> dict[str, Any] | None:
    """Resolve ``location`` to (display_name, lat, lon) via Nominatim.

    Returns ``None`` on a zero-results response. Raises
    :class:`httpx.HTTPError` on transport failure; the caller maps it
    to the network-error taxonomy row.
    """
    key = _cache_key(location)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    lock = _get_nominatim_lock()
    async with lock:
        # Per-acquire delay: ensure at least
        # ``_NOMINATIM_RATE_LIMIT_INTERVAL_SECONDS`` between successive
        # outgoing requests against the public instance.
        global _NOMINATIM_LAST_CALL_AT
        now = time.monotonic()
        wait = _NOMINATIM_RATE_LIMIT_INTERVAL_SECONDS - (now - _NOMINATIM_LAST_CALL_AT)
        if wait > 0:
            await asyncio.sleep(wait)
        response = await client.get(
            settings.nominatim_base_url + "/search",
            params={"q": location, "format": "json", "limit": 1},
            timeout=_NOMINATIM_TIMEOUT_SECONDS,
        )
        _NOMINATIM_LAST_CALL_AT = time.monotonic()

    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        return None
    top = payload[0]
    try:
        resolved = {
            "display_name": str(top["display_name"]),
            "lat": float(top["lat"]),
            "lon": float(top["lon"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    _cache_put(key, resolved)
    return resolved


# --- POI query (Overpass) --------------------------------------------------


def _build_overpass_query(
    *,
    filters: tuple[str, ...],
    lat: float,
    lon: float,
    radius_km: int,
) -> str:
    """Build an Overpass QL ``union`` query for the filter list."""
    radius_m = radius_km * 1000
    union_clauses = []
    for entry in filters:
        key, _, value = entry.partition("=")
        # node, way, and relation — coverage of all three forms is the
        # whole reason the URL field accepts way/<id> too.
        for kind in ("node", "way", "relation"):
            union_clauses.append(f'{kind}["{key}"="{value}"](around:{radius_m},{lat},{lon});')
    body = "\n  ".join(union_clauses)
    return f"[out:json][timeout:25];\n(\n  {body}\n);\nout center tags;"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    d_lat = lat2_r - lat1_r
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(d_lon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _format_address(tags: dict[str, Any], fallback: str) -> str:
    """Assemble an address line from ``addr:*`` tags, falling back."""
    parts: list[str] = []
    house = tags.get("addr:housenumber")
    street = tags.get("addr:street")
    if house and street:
        parts.append(f"{house} {street}")
    elif street:
        parts.append(str(street))
    for key in ("addr:city", "addr:town", "addr:village"):
        value = tags.get(key)
        if value:
            parts.append(str(value))
            break
    postcode = tags.get("addr:postcode")
    if postcode:
        parts.append(str(postcode))
    if parts:
        return ", ".join(parts)
    return fallback


def _osm_url(kind: str, element_id: int | str) -> str:
    return f"https://www.openstreetmap.org/{kind}/{element_id}"


def _parse_overpass(
    *,
    payload: dict[str, Any],
    centre_lat: float,
    centre_lon: float,
    fallback_locality: str,
) -> list[dict[str, Any]]:
    """Parse an Overpass response into a sorted, deduplicated result list."""
    elements = payload.get("elements") or []
    seen_ids: set[tuple[str, Any]] = set()
    rows: list[dict[str, Any]] = []
    for element in elements:
        kind = element.get("type")
        element_id = element.get("id")
        if kind not in ("node", "way", "relation") or element_id is None:
            continue
        identity = (kind, element_id)
        if identity in seen_ids:
            continue
        seen_ids.add(identity)
        tags = element.get("tags") or {}
        name = tags.get("name")
        if not name:
            # Without a name the user has nothing to act on — skip.
            continue
        if kind == "node":
            lat = element.get("lat")
            lon = element.get("lon")
        else:
            centre = element.get("center") or {}
            lat = centre.get("lat")
            lon = centre.get("lon")
        if lat is None or lon is None:
            continue
        try:
            distance = _haversine_km(centre_lat, centre_lon, float(lat), float(lon))
        except (TypeError, ValueError):
            continue
        phone = tags.get("phone") or tags.get("contact:phone") or ""
        rows.append(
            {
                "name": str(name),
                "address": _format_address(tags, fallback_locality),
                "phone": str(phone),
                "url": _osm_url(kind, element_id),
                "distance_km": round(distance, 1),
            }
        )
    rows.sort(key=lambda r: r["distance_km"])
    return rows[:_TOP_RESULTS]


async def _query_overpass(
    *,
    query: str,
    url: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    response = await client.post(
        url,
        content=query.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
        timeout=_OVERPASS_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return {"elements": []}
    return payload


async def _query_overpass_with_failover(
    *,
    query: str,
    settings: Settings,
    client: httpx.AsyncClient,
    log: Any,
    radius_km: int,
    resolved_locality: str,
) -> dict[str, Any] | None:
    """Try the configured Overpass URL, then each fallback mirror.

    Returns the first successful payload. Returns ``None`` when every
    mirror raises — the caller maps that to the network-error
    failure-taxonomy row. Per-mirror failures are logged at warning
    with the offending URL so an operator can correlate flapping to a
    specific host.
    """
    urls = (settings.overpass_base_url, *_OVERPASS_FALLBACK_MIRRORS)
    for index, url in enumerate(urls):
        if index > 0:
            await asyncio.sleep(_OVERPASS_RETRY_BACKOFF_SECONDS)
        try:
            return await _query_overpass(query=query, url=url, client=client)
        except httpx.HTTPError as exc:
            log.warning(
                "clinician.upstream_failed",
                source="overpass",
                mirror_url=url,
                error=str(exc),
                error_type=type(exc).__name__,
                radius_km=radius_km,
                resolved_locality=resolved_locality,
            )
        except Exception as exc:  # noqa: BLE001 — degrade rather than crash
            log.warning(
                "clinician.upstream_failed",
                source="overpass",
                mirror_url=url,
                error=str(exc),
                error_type=type(exc).__name__,
                radius_km=radius_km,
                resolved_locality=resolved_locality,
            )
    return None


# --- Public entrypoint ------------------------------------------------------


async def find_clinics(
    condition_id: str,
    location: str,
    *,
    settings: Settings,
) -> str:
    """Find up to five healthcare providers near ``location``.

    Returns a JSON-encoded string. On success, the payload contains
    ``specialist_label``, ``location_resolved``, ``radius_km``,
    ``results`` (list of clinic dicts), and ``count``. On any failure
    path, returns ``{"error": "<verbalisable string>"}`` — the failure
    taxonomy is exhaustive and exceptions never escape this function.
    """
    log = _log.bind(condition_id=condition_id, location=location)

    condition = CONDITIONS.get(condition_id)
    if condition is None:
        log.warning("clinician.unknown_condition")
        return _error_payload(_ERR_UNKNOWN_CONDITION)

    if not location or not location.strip():
        log.warning("clinician.empty_location")
        return _error_payload(_ERR_EMPTY_LOCATION)

    contact_email = settings.osm_contact_email
    if not contact_email:
        log.warning("clinician.misconfigured", reason="missing_osm_contact_email")
        return _error_payload(_err_network(condition.specialist_label, location.strip()))

    try:
        return await asyncio.wait_for(
            _run(condition_id, location.strip(), settings=settings, log=log),
            timeout=_TOTAL_BUDGET_SECONDS,
        )
    except TimeoutError:
        log.warning(
            "clinician.budget_exceeded",
            source="total",
            timeout_seconds=_TOTAL_BUDGET_SECONDS,
        )
        return _error_payload(_err_network(condition.specialist_label, location.strip()))


async def _run(
    condition_id: str,
    location: str,
    *,
    settings: Settings,
    log: Any,
) -> str:
    """Inner orchestration body, run under :func:`asyncio.wait_for`."""
    condition = CONDITIONS[condition_id]
    contact_email = settings.osm_contact_email or ""
    headers = {"User-Agent": _user_agent(contact_email)}

    async with httpx.AsyncClient(headers=headers) as client:
        # --- Geocode --------------------------------------------------
        try:
            geocoded = await _geocode(location, settings=settings, client=client)
        except httpx.HTTPError as exc:
            log.warning(
                "clinician.upstream_failed",
                source="nominatim",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return _error_payload(_err_network(condition.specialist_label, location))
        except Exception as exc:  # noqa: BLE001 — degrade rather than crash
            log.warning(
                "clinician.upstream_failed",
                source="nominatim",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return _error_payload(_err_network(condition.specialist_label, location))

        if geocoded is None:
            log.warning("clinician.zero_results", source="nominatim")
            return _error_payload(_err_zero_geocode(location))

        resolved_locality = geocoded["display_name"]
        lat = geocoded["lat"]
        lon = geocoded["lon"]

        # --- Overpass radius-fallback ladder --------------------------
        results: list[dict[str, Any]] = []
        used_radius = _RADIUS_LADDER_KM[-1]
        for radius_km in _RADIUS_LADDER_KM:
            query = _build_overpass_query(
                filters=condition.specialist_osm_filters,
                lat=lat,
                lon=lon,
                radius_km=radius_km,
            )
            payload = await _query_overpass_with_failover(
                query=query,
                settings=settings,
                client=client,
                log=log,
                radius_km=radius_km,
                resolved_locality=resolved_locality,
            )
            if payload is None:
                return _error_payload(_err_network(condition.specialist_label, location))

            results = _parse_overpass(
                payload=payload,
                centre_lat=lat,
                centre_lon=lon,
                fallback_locality=resolved_locality,
            )
            if results:
                used_radius = radius_km
                break

        if not results:
            log.warning(
                "clinician.zero_results",
                source="overpass",
                resolved_locality=resolved_locality,
                radius_km=_RADIUS_LADDER_KM[-1],
            )
            return _error_payload(_err_zero_results(condition.specialist_label, resolved_locality))

        log.info(
            "clinician.success",
            resolved_locality=resolved_locality,
            radius_km=used_radius,
            count=len(results),
        )
        return json.dumps(
            {
                "specialist_label": condition.specialist_label,
                "location_resolved": resolved_locality,
                "radius_km": used_radius,
                "results": results,
                "count": len(results),
            }
        )


__all__ = ["find_clinics"]
