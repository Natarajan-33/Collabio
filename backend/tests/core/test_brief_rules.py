from datetime import date

import pytest

from app.core.brief_rules import (
    BRIEF_FIELD_LABELS,
    field_error,
    is_launchable,
    missing_fields,
    violations,
)
from app.schemas.briefs import REQUIRED_BRIEF_FIELDS, BriefFields
from app.schemas.packages import RuleViolation

TODAY = date(2026, 10, 10)

COMPLETE = BriefFields(
    brand_name="Lumen Audio",
    product_name="Halo Earbuds",
    product_summary="Open-ear earbuds built for long days.",
    deliverables_count=3,
    deliverables_format="short_video",
    deliverable_length_s=30,
    go_live_by=date(2026, 11, 15),
    budget_ceiling_cents=120000,
    ask_price_cents=100000,
    negotiation_ask="Three short videos at the listed rate",
    flexibility=["timeline"],
    contact_email="team@lumen.example",
)


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("product_summary", "x" * 201, "Keep the product summary to 200 characters."),
        ("deliverables_count", 0, "Ask for at least one deliverable."),
        ("deliverable_length_s", 0, "The video length must be more than 0 seconds."),
        ("go_live_by", TODAY, "The go-live date must be in the future."),
        ("budget_ceiling_cents", 0, "The budget ceiling must be more than $0."),
        ("ask_price_cents", -5, "The opening ask must be more than $0."),
        ("flexibility", ["none", "price"], "“None” can't be combined with other flexibility."),
        ("contact_email", "not-an-email", "Enter a valid contact email."),
    ],
)
def test_field_error(field, value, message):
    assert field_error(field, value, TODAY) == message


@pytest.mark.parametrize(
    "field,value",
    [
        ("brand_name", "Lumen"),
        ("product_name", "Halo"),
        ("product_summary", "x" * 200),
        ("deliverables_count", 1),
        ("deliverables_format", "story"),
        ("deliverable_length_s", 15),
        ("go_live_by", date(2026, 10, 11)),
        ("budget_ceiling_cents", 1),
        ("ask_price_cents", 1),
        ("negotiation_ask", "Price"),
        ("flexibility", ["none"]),
        ("flexibility", ["price", "timeline"]),
        ("flexibility_note", "Open to bundling"),
        ("contact_email", "a@b.co"),
    ],
)
def test_valid_values_have_no_error(field, value):
    assert field_error(field, value, TODAY) is None


@pytest.mark.parametrize("field", list(BRIEF_FIELD_LABELS))
def test_clearing_a_field_is_never_an_error(field):
    assert field_error(field, None, TODAY) is None


def test_missing_in_required_order():
    brief = BriefFields(brand_name="Lumen", product_name=" ")
    assert missing_fields(brief) == list(REQUIRED_BRIEF_FIELDS[1:])


def test_empty_flexibility_is_missing():
    assert missing_fields(COMPLETE.model_copy(update={"flexibility": []})) == ["flexibility"]


def test_ask_above_ceiling_is_a_violation():
    brief = COMPLETE.model_copy(update={"ask_price_cents": 130000, "budget_ceiling_cents": 120000})
    assert violations(brief, TODAY) == [
        RuleViolation(
            field="ask_price_cents", message="The opening ask can't be above the budget ceiling."
        )
    ]


def test_field_violations_are_reported():
    brief = COMPLETE.model_copy(update={"contact_email": "nope", "deliverables_count": 0})
    assert {v.field for v in violations(brief, TODAY)} == {"contact_email", "deliverables_count"}


def test_complete_brief_is_launchable():
    assert is_launchable(COMPLETE, TODAY)


def test_incomplete_or_violating_brief_is_not_launchable():
    assert not is_launchable(COMPLETE.model_copy(update={"brand_name": None}), TODAY)
    assert not is_launchable(COMPLETE.model_copy(update={"go_live_by": TODAY}), TODAY)


def test_labels_cover_every_required_field():
    assert set(REQUIRED_BRIEF_FIELDS) <= set(BRIEF_FIELD_LABELS)
