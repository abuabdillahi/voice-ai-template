"""Typed application settings loaded from environment variables.

The settings module is the single seam between the application and process
environment. Every other module that needs configuration imports
`get_settings()` rather than reading `os.environ` directly. This keeps the
tree of environment dependencies discoverable and testable.

The fields here track the variables documented in `.env.example` at the
repo root. Issues 05+ extend this class with their own variables.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide settings backed by environment variables.

    All Supabase fields are required because every later layer (auth,
    persistence, RLS) depends on them. The application fails fast at
    construction time if any are missing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # --- Supabase ---
    supabase_url: str = Field(..., description="Supabase project URL.")
    # The publishable (formerly "anon") key identifies the project to
    # PostgREST. Reads the new env var first; falls back to
    # SUPABASE_ANON_KEY for `.env` files cloned before the 2026 rename.
    supabase_publishable_key: str = Field(
        ...,
        description="Supabase publishable (formerly anon) API key.",
        validation_alias=AliasChoices("supabase_publishable_key", "supabase_anon_key"),
    )
    # Optional override for the JWKS endpoint. Self-hosted Supabase
    # deployments at non-standard paths can set this; otherwise the
    # verifier derives it from `supabase_url`.
    supabase_jwks_url: str | None = Field(
        default=None,
        description=(
            "Override URL for the Supabase JWKS endpoint. When unset, "
            "defaults to {supabase_url}/auth/v1/.well-known/jwks.json."
        ),
    )
    # Legacy HS256 secret. Retained as optional for backward compatibility
    # with `.env` files cloned before the JWKS migration; the verifier no
    # longer consults it.
    supabase_jwt_secret: str | None = Field(
        default=None,
        description="Deprecated: legacy HS256 JWT secret. No longer used.",
    )

    # --- LiveKit (realtime media plane) ---
    # All three LiveKit fields are required. The API mints tokens against
    # the secret, the agent worker dials the URL, and a missing key in
    # any environment is a configuration bug the application should
    # surface at boot rather than at first request.
    livekit_url: str = Field(
        ...,
        description=(
            "WebSocket URL of the LiveKit server. LiveKit Cloud in "
            "development (wss://<project>.livekit.cloud) or the "
            "self-hosted server in production."
        ),
    )
    livekit_api_key: str = Field(..., description="LiveKit API key.")
    livekit_api_secret: str = Field(..., description="LiveKit API secret.")

    # --- OpenAI ---
    openai_api_key: str = Field(
        ..., description="OpenAI API key used by the default realtime model."
    )

    # --- mem0 (episodic memory) ---
    # mem0 stores vectors in pgvector against the same Supabase Postgres,
    # but its connection is pooled at the database (not REST) layer so it
    # needs the raw Postgres URL rather than the Supabase REST URL. The
    # variable is optional because the unit-test path mocks the mem0
    # client at the seam — production deployments must provide it.
    mem0_postgres_url: str = Field(
        default="",
        description=(
            "PostgreSQL connection URL for mem0's pgvector backend. "
            "Typically the same Postgres instance Supabase manages, "
            "addressed via the connection-pooler URL. Empty in tests."
        ),
    )
    mem0_collection: str = Field(
        default="mem0_memories",
        description=(
            "Name of the pgvector table mem0 writes memories to. "
            "Must match the table created in `0003_mem0_memories.sql`."
        ),
    )
    mem0_embedding_dims: int = Field(
        default=1536,
        description=(
            "Dimensionality of the embedding model mem0 uses. Must match "
            "the `vector(N)` column in the migration. The default tracks "
            "OpenAI's text-embedding-3-small."
        ),
    )

    # --- Safety classifier ---
    # The second layer of the red-flag detector (slice 06) is a
    # gpt-4o-mini classifier with structured output. It reuses
    # `openai_api_key`; the model id is configurable so a future
    # safety-quality upgrade can swap to a different OpenAI model
    # without code edits. See `core.safety.classify`.
    safety_classifier_model: str = Field(
        default="gpt-4o-mini",
        description=(
            "OpenAI model id used by the parallel safety classifier. "
            "Reads `OPENAI_API_KEY`. Defaults to gpt-4o-mini."
        ),
    )

    # --- OpenStreetMap (clinician finder) ---
    # The contact email is the OSMF usage-policy obligation: the
    # User-Agent on every Nominatim/Overpass request embeds it so the
    # public instance can reach an operator if our traffic misbehaves.
    # When unset, ``core.clinician.find_clinics`` returns the
    # network-unavailable failure string and the agent worker filters
    # the ``find_clinician`` tool out of the registered tool set so the
    # feature is silently disabled rather than surfacing a runtime error
    # mid-conversation. The base URLs are overridable so tests and
    # alternative hosts (e.g. self-hosted Overpass) can swap them.
    osm_contact_email: str | None = Field(
        default=None,
        description=(
            "Operator contact email embedded in the User-Agent on every "
            "Nominatim/Overpass request (OSMF usage-policy requirement). "
            "When unset, the find_clinician tool is disabled."
        ),
    )
    nominatim_base_url: str = Field(
        default="https://nominatim.openstreetmap.org",
        description="Base URL of the Nominatim geocoding service.",
    )
    overpass_base_url: str = Field(
        default="https://overpass-api.de/api/interpreter",
        description="Base URL of the Overpass POI-search interpreter.",
    )

    # --- HTTP / observability ---
    cors_origins: str = Field(
        default="http://localhost:5173",
        description=(
            "Comma-separated list of allowed CORS origins. The Vite dev server "
            "default is included unconditionally."
        ),
    )
    log_level: str = Field(default="INFO", description="Standard Python logging level.")
    environment: str = Field(
        default="development",
        description="Free-form environment label; controls log formatting.",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed list of CORS origins; empty entries are dropped."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings`, loaded once and cached.

    Call sites should use this rather than instantiating `Settings()`
    directly so that tests can override the cache via
    ``get_settings.cache_clear()``.
    """
    return Settings()  # type: ignore[call-arg]
