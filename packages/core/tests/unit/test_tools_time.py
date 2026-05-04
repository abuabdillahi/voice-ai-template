"""Unit tests for `core.tools.examples.get_current_time`."""

from __future__ import annotations

import pytest
from core.tools.examples import get_current_time


@pytest.mark.asyncio
async def test_known_timezone_returns_iso_summary() -> None:
    result = await get_current_time(timezone="UTC")
    assert "UTC" in result
    # ISO format includes a `T` between date and time.
    assert "T" in result


@pytest.mark.asyncio
async def test_unknown_timezone_returns_graceful_message() -> None:
    result = await get_current_time(timezone="Mars/Olympus_Mons")
    assert "don't recognise" in result.lower()
    assert "Mars/Olympus_Mons" in result


@pytest.mark.asyncio
async def test_default_timezone_is_utc() -> None:
    result = await get_current_time()
    assert "UTC" in result
