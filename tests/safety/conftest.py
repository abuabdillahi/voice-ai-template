"""pytest fixtures for the safety eval harness.

The runner imports ``agent.session`` lazily at script-run time; this
conftest is intentionally minimal — pytest-asyncio is configured at the
repo-root ``pyproject.toml`` so async tests in this package are picked
up by default.
"""

from __future__ import annotations
