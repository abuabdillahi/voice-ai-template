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

from pydantic import Field
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
    )

    # --- Supabase ---
    supabase_url: str = Field(..., description="Supabase project URL.")
    supabase_anon_key: str = Field(..., description="Supabase anon/public API key.")
    supabase_jwt_secret: str = Field(
        ..., description="HS256 secret used by Supabase to sign user JWTs."
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
