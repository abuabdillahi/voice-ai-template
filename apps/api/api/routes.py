"""HTTP route handlers.

Each new route is added here (or in a domain-specific submodule
imported from here) so that `app.py` stays focused on application
assembly. Handlers translate HTTP into `core` calls and never contain
business logic.
"""

from __future__ import annotations

from typing import Annotated

from core.auth import User, get_current_user
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: str


class MeResponse(BaseModel):
    """Authenticated user, projected for the wire."""

    id: str
    email: str


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Liveness probe. Returns 200 with a static payload."""
    return HealthResponse(status="ok")


@router.get("/me", response_model=MeResponse, tags=["auth"])
def me(current_user: Annotated[User, Depends(get_current_user)]) -> MeResponse:
    """Return the authenticated user's id and email."""
    return MeResponse(id=str(current_user.id), email=current_user.email)
