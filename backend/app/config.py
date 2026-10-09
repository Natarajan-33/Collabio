from functools import lru_cache
from pathlib import Path

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
    supabase_secret_key: str = ""
    supabase_db_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    supabase_jwks_url: str = "http://127.0.0.1:54321/auth/v1/.well-known/jwks.json"

    gemini_api_key: str = ""
    gemini_text_model: str = "gemini-3.8-flash"
    gemini_embed_model: str = "gemini-embedding-2"

    elevenlabs_api_key: str = ""

    frontend_origin: str = "http://localhost:3000"

    demo_brand_email: str = ""
    demo_password: str = ""
    demo_helper_phone: str = ""
    demo_helper_email: str = ""

    @property
    def database_configured(self) -> bool:
        """False while SUPABASE_DB_URL is blank or still the dashboard placeholder."""
        dsn = self.supabase_db_url
        return bool(dsn.strip()) and DSN_PLACEHOLDER not in dsn


@lru_cache
def get_settings() -> Settings:
    return Settings()
