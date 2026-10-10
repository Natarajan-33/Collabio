"""Validation of the POST /onboarding body (no database needed)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.me import BrandOnboarding, CreatorOnboarding, OnboardingRequest

onboarding_request = TypeAdapter(OnboardingRequest)

BRAND = {
    "role": "brand",
    "display_name": "Maya Chen",
    "company_name": "Lumen Audio",
    "category": "consumer_tech",
    "product_name": "Lumen Pods",
    "product_summary": "Wireless earbuds with 40-hour battery",
}
CREATOR = {
    "role": "creator",
    "display_name": "Priya Raman",
    "handle": "priyareviews",
    "niches": ["consumer_tech"],
    "region": "IN",
}


def test_role_selects_the_model():
    assert isinstance(onboarding_request.validate_python(BRAND), BrandOnboarding)
    assert isinstance(onboarding_request.validate_python(CREATOR), CreatorOnboarding)


def test_creator_input_is_normalized():
    req = onboarding_request.validate_python(
        {
            **CREATOR,
            "display_name": "  Priya Raman ",
            "handle": " @Priya.Reviews ",
            "niches": ["beauty", "consumer_tech", "beauty"],
        }
    )
    assert req.display_name == "Priya Raman"
    assert req.handle == "priya.reviews"
    assert req.niches == ["beauty", "consumer_tech"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({**CREATOR, "role": "admin"}, id="unknown-role"),
        pytest.param({**CREATOR, "niches": ["astrology"]}, id="unknown-niche"),
        pytest.param({**CREATOR, "niches": []}, id="no-niches"),
        pytest.param({**CREATOR, "handle": "priya reviews"}, id="handle-with-space"),
        pytest.param({**CREATOR, "handle": "@"}, id="handle-too-short"),
        pytest.param({**CREATOR, "display_name": "   "}, id="blank-name"),
        pytest.param({**CREATOR, "region": "India"}, id="region-name-not-code"),
        pytest.param({**CREATOR, "region": "Narnia"}, id="unknown-region"),
        pytest.param({k: v for k, v in CREATOR.items() if k != "region"}, id="no-region"),
        pytest.param({**BRAND, "category": "furniture"}, id="unknown-category"),
        pytest.param({**BRAND, "product_summary": "x" * 201}, id="summary-too-long"),
        pytest.param({k: v for k, v in BRAND.items() if k != "product_name"}, id="no-product"),
    ],
)
def test_invalid_body_rejected(body):
    with pytest.raises(ValidationError):
        onboarding_request.validate_python(body)
