"""Agent worker entrypoint.

Hands control to the livekit-agents CLI, which manages the worker
lifecycle: registering with the LiveKit server, accepting dispatched
jobs, calling our :func:`agent.session.entrypoint` per job, and
handling SIGTERM gracefully.

Invoke with `python -m agent dev` for a developer-friendly shell or
`python -m agent start` for production. The LiveKit CLI subcommands
are documented at https://docs.livekit.io/agents/.
"""

from __future__ import annotations

from livekit.agents import cli

from agent.session import worker_options


def main() -> None:
    """Run the LiveKit Agents worker."""
    cli.run_app(worker_options())


if __name__ == "__main__":
    main()
