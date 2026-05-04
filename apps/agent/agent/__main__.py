"""Agent worker stub.

Logs a structured startup line and then sleeps indefinitely. The real
LiveKit Agents worker (room subscription, voice loop, tool calling) is
wired up in issue 05; this stub exists so the container has a sensible
PID 1 process and so docker compose can bring the service to a running
state for end-to-end smoke tests.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone


def _log(event: str, **fields: object) -> None:
    """Emit a single JSON line to stdout."""
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": "info",
        "service": "agent",
        "event": event,
        **fields,
    }
    print(json.dumps(payload), flush=True)


def main() -> int:
    _log("agent.startup", message="agent stub running; real worker arrives in issue 05")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        _log("agent.shutdown", reason="keyboard_interrupt")
        return 0


if __name__ == "__main__":
    sys.exit(main())
