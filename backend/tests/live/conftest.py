"""Live tests call real third-party APIs with the developer's keys from backend/.env.

They are deselected by default (`addopts = "-m 'not live'"`); run them with `-m live`.
"""

import pytest

from app.config import Settings, get_settings


@pytest.fixture
def settings() -> Settings:
    return get_settings()
