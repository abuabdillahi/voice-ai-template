"""FastAPI HTTP backend entrypoint.

Exposes a minimal `/health` endpoint so that container orchestrators and
local docker compose stacks can verify the service is alive. The richer
HTTP surface (auth, conversation routes, etc.) arrives in subsequent issues.
"""

from fastapi import FastAPI

app = FastAPI(title="voice-ai api", version="0.0.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Returns 200 with a static payload."""
    return {"status": "ok"}
