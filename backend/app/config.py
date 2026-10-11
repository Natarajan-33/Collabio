from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env, resolved from this file so the app loads it from any working directory.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# Supabase dashboard connection strings contain "[YOUR-PASSWORD]" until filled in.
DSN_PLACEHOLDER = "[YOUR-"


class Settings(BaseSettings):
    """Backend configuration read from the environment and `backend/.env`.

    Every field has a default so the app starts without a `.env` file; secrets
    default to empty strings and the Supabase URLs to the local stack.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # a blank `KEY=` in .env falls back to the default
        extra="ignore",  # .env may hold variables later milestones add
    )

    supabase_url: str = "http://127.0.0.1:54321"
    # Fields marked repr=False hold secrets (or a DSN with a password): they stay out of
    # repr(), so logs and pytest tracebacks that show a Settings never print them.
    supabase_secret_key: str = Field("", repr=False)
    supabase_db_url: str = Field(
        "postgresql://postgres:postgres@127.0.0.1:54322/postgres", repr=False
    )
    supabase_jwks_url: str = "http://127.0.0.1:54321/auth/v1/.well-known/jwks.json"

    gemini_api_key: str = Field("", repr=False)
    gemini_text_model: str = "gemini-3.5-flash-lite"
    gemini_embed_model: str = "gemini-embedding-2"

    elevenlabs_api_key: str = Field("", repr=False)
    elevenlabs_brief_agent_id: str = ""
    elevenlabs_negotiation_agent_id: str = ""
    elevenlabs_phone_number_id: str = ""
    elevenlabs_webhook_secret: str = Field("", repr=False)
    elevenlabs_tool_secret: str = Field("", repr=False)

    resend_api_key: str = Field("", repr=False)
    resend_from: str = ""
    resend_inbound_domain: str = ""

    # Where ElevenLabs reaches the tool webhooks, and where emailed links point.
    public_backend_url: str = "http://localhost:8000"
    public_frontend_url: str = "http://localhost:3000"
    workers_enabled: bool = True

    # One origin, or several comma-separated (production URLs).
    frontend_origin: str = "http://localhost:3000"
    # Optional RE2 regex for extra origins (e.g. Vercel preview URLs that change every deploy).
    frontend_origin_regex: str = ""

    demo_brand_email: str = ""
    demo_password: str = Field("", repr=False)
    demo_helper_phone: str = ""
    demo_helper_email: str = ""

    @property
    def frontend_origins(self) -> list[str]:
        """CORS allowlist: `FRONTEND_ORIGIN` split on commas, trimmed, no empties."""
        return [part.strip() for part in self.frontend_origin.split(",") if part.strip()]

    @property
    def database_configured(self) -> bool:
        """False while SUPABASE_DB_URL is blank or still the dashboard placeholder."""
        dsn = self.supabase_db_url
        return bool(dsn.strip()) and DSN_PLACEHOLDER not in dsn


@lru_cache
def get_settings() -> Settings:
    return Settings()
