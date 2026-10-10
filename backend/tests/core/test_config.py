"""Settings: secrets stay out of repr(), and the defaults the app relies on."""

import pytest

from app.config import Settings

SECRETS = {
    "supabase_secret_key": "dummy-supabase-secret-key",
    "supabase_db_url": "postgresql://postgres:dummy-db-password@db.example.invalid:5432/postgres",
    "gemini_api_key": "dummy-gemini-api-key",
    "elevenlabs_api_key": "dummy-elevenlabs-api-key",
    "demo_password": "dummy-demo-password",
}


def test_repr_and_str_contain_no_secret_values():
    settings = Settings(_env_file=None, **SECRETS)

    for text in (repr(settings), str(settings)):
        for field, value in SECRETS.items():
            assert value not in text, f"{field} is printed"
        assert "dummy-db-password" not in text
    # Non-secret fields still show, so the repr stays useful.
    assert "gemini_text_model=" in repr(settings)


def test_secrets_are_still_readable():
    settings = Settings(_env_file=None, **SECRETS)

    for field, value in SECRETS.items():
        assert getattr(settings, field) == value


def test_default_text_model_is_flash_lite(monkeypatch):
    monkeypatch.delenv("GEMINI_TEXT_MODEL", raising=False)
    assert Settings(_env_file=None).gemini_text_model == "gemini-3.5-flash-lite"


def test_secrets_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-from-env")
    settings = Settings(_env_file=None)
    assert settings.gemini_api_key == "dummy-from-env"
    assert "dummy-from-env" not in repr(settings)


@pytest.mark.parametrize("field", list(SECRETS))
def test_every_secret_field_is_hidden_from_repr(field):
    assert Settings.model_fields[field].repr is False
