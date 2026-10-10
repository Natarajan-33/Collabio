from app.core.package_rules import (
    draft_violations,
    merge_package_draft,
    missing_fields,
    patch_package_draft,
    terms_from_draft,
    validate_package,
)
from app.schemas.packages import Addon, Extra, PackageDraft, PackageTerms
from tests.core.factories import make_pkg


def test_validate_accepts_valid_package():
    assert validate_package(make_pkg(), creator_niches=["consumer_tech"]) == []


def test_validate_rejects_niche_outside_creator_domains():
    v = validate_package(make_pkg(niche="beauty"), creator_niches=["consumer_tech"])
    assert [x.field for x in v] == ["niche"]


def test_validate_rejects_duplicate_addon_names():
    pkg = make_pkg(
        addons=[
            Addon(name="Rush", price_cents=1, unit="item"),
            Addon(name="rush", price_cents=2, unit="item"),
        ]
    )
    assert "addons" in [x.field for x in validate_package(pkg, ["consumer_tech"])]


def test_validate_rejects_duplicate_extra_names():
    pkg = make_pkg(
        extras=[
            Extra(name="Raw footage", price_cents=5000),
            Extra(name="raw footage ", price_cents=6000),
        ]
    )
    assert [x.field for x in validate_package(pkg, ["consumer_tech"])] == ["extras"]


def test_validate_rejects_values_the_database_would_refuse():
    pkg = make_pkg(
        name="  ", volume_count=0, base_price_cents=0, lead_time_days=-1, slots_per_month=-1
    )
    assert [x.field for x in validate_package(pkg, ["consumer_tech"])] == [
        "name",
        "volume_count",
        "base_price_cents",
        "slots_per_month",
        "lead_time_days",
    ]


def test_validate_rejects_non_positive_addon_and_extra_prices():
    pkg = make_pkg(
        addons=[Addon(name="Extra video", price_cents=0, unit="video")],
        extras=[Extra(name="Raw footage", price_cents=-100)],
    )
    assert [x.field for x in validate_package(pkg, ["consumer_tech"])] == ["addons", "extras"]


def test_validate_violation_has_message():
    [violation] = validate_package(make_pkg(niche="beauty"), creator_niches=["consumer_tech"])
    assert violation.message


def test_missing_fields_lists_required_in_order():
    assert missing_fields(PackageDraft(name="Duo")) == [
        "content_type",
        "niche",
        "volume_count",
        "volume_basis",
        "base_price_cents",
        "preferred_channel",
    ]


def test_missing_fields_all_when_empty_and_blank_name_counts_as_missing():
    assert missing_fields(PackageDraft()) == [
        "name",
        "content_type",
        "niche",
        "volume_count",
        "volume_basis",
        "base_price_cents",
        "preferred_channel",
    ]
    assert missing_fields(PackageDraft(name=" "))[0] == "name"


def test_missing_fields_empty_for_complete_draft():
    draft = PackageDraft(
        name="Duo",
        content_type="short_video",
        niche="consumer_tech",
        volume_count=2,
        volume_basis="per_contract",
        base_price_cents=100000,
        preferred_channel="phone_ok",
    )
    assert missing_fields(draft) == []


def test_complete_draft_converts_to_package_terms_without_lead_time():
    draft = PackageDraft(
        name="Duo",
        content_type="short_video",
        niche="consumer_tech",
        volume_count=2,
        volume_basis="per_contract",
        base_price_cents=100000,
        preferred_channel="phone_ok",
    )
    assert missing_fields(draft) == []
    terms = PackageTerms(**draft.model_dump(exclude_none=True))
    assert terms.lead_time_days is None and terms.slots_per_month is None
    assert terms.currency == "USD"


def test_validate_accepts_unset_lead_time():
    assert validate_package(make_pkg(lead_time_days=None), ["consumer_tech"]) == []


def test_merge_keeps_current_when_extracted_null_and_merges_addons():
    cur = PackageDraft(
        base_price_cents=100000, addons=[Addon(name="Extra video", price_cents=40000, unit="video")]
    )
    ext = PackageDraft(
        volume_count=2, addons=[Addon(name="extra video", price_cents=45000, unit="video")]
    )
    out = merge_package_draft(cur, ext)
    assert out.base_price_cents == 100000 and out.volume_count == 2
    assert [(a.name, a.price_cents) for a in out.addons] == [("extra video", 45000)]


def test_merge_overwrites_scalars_with_non_null_extracted_values():
    cur = PackageDraft(name="Duo", base_price_cents=100000, lead_time_days=14)
    ext = PackageDraft(base_price_cents=120000, lead_time_days=0)
    out = merge_package_draft(cur, ext)
    assert (out.name, out.base_price_cents, out.lead_time_days) == ("Duo", 120000, 0)


def test_merge_keeps_unmatched_named_items_and_appends_new_ones():
    cur = PackageDraft(
        addons=[
            Addon(name="Extra video", price_cents=40000, unit="video"),
            Addon(name="Rush", price_cents=20000, unit="item"),
        ],
        extras=[Extra(name="Raw footage", price_cents=5000)],
    )
    ext = PackageDraft(
        addons=[
            Addon(name="Whitelisting", price_cents=30000, unit="item"),
            Addon(name="RUSH", price_cents=25000, unit="item"),
        ],
        extras=[Extra(name="Thumbnail", price_cents=2000)],
    )
    out = merge_package_draft(cur, ext)
    assert [(a.name, a.price_cents) for a in out.addons] == [
        ("Extra video", 40000),
        ("RUSH", 25000),
        ("Whitelisting", 30000),
    ]
    assert [e.name for e in out.extras] == ["Raw footage", "Thumbnail"]


def test_merge_unions_included_and_freebies_case_insensitively():
    cur = PackageDraft(included=["Script approval", "1 revision"], freebies=["Story shoutout"])
    ext = PackageDraft(included=["1 Revision", "Usage rights 30 days"], freebies=[])
    out = merge_package_draft(cur, ext)
    assert out.included == ["Script approval", "1 Revision", "Usage rights 30 days"]
    assert out.freebies == ["Story shoutout"]


def test_merge_does_not_mutate_inputs():
    cur = PackageDraft(addons=[Addon(name="Extra video", price_cents=40000, unit="video")])
    ext = PackageDraft(addons=[Addon(name="Rush", price_cents=20000, unit="item")])
    merge_package_draft(cur, ext)
    assert [a.name for a in cur.addons] == ["Extra video"]
    assert [a.name for a in ext.addons] == ["Rush"]


# Violations while the draft is still being filled in ------------------------------------


def test_draft_violations_report_only_fields_the_draft_has():
    draft = PackageDraft(niche="beauty", volume_count=0)
    got = draft_violations(draft, creator_niches=["consumer_tech"])
    assert [v.field for v in got] == ["niche", "volume_count"]


def test_draft_violations_ignore_missing_fields():
    # Nothing said yet: an unset name, price or niche is "missing", not a rule violation.
    assert draft_violations(PackageDraft(), creator_niches=["consumer_tech"]) == []
    assert draft_violations(PackageDraft(name="  "), creator_niches=[]) == []


def test_draft_violations_for_a_complete_draft_match_validate_package():
    draft = PackageDraft(**make_pkg(niche="beauty", lead_time_days=-2).model_dump())
    assert draft_violations(draft, ["consumer_tech"]) == validate_package(
        terms_from_draft(draft), ["consumer_tech"]
    )


def test_terms_from_draft_fills_defaults_for_unset_optional_fields():
    draft = PackageDraft(**make_pkg(lead_time_days=None).model_dump())
    draft.currency = None
    terms = terms_from_draft(draft)
    assert terms.currency == "USD" and terms.lead_time_days is None


# Patching a saved package ------------------------------------------------------------------


def test_patch_changes_only_the_fields_that_were_sent():
    saved = PackageDraft(**make_pkg(lead_time_days=14).model_dump())
    patched = patch_package_draft(saved, PackageDraft(base_price_cents=90000))
    assert patched.base_price_cents == 90000
    assert patched.name == saved.name and patched.lead_time_days == 14


def test_patch_replaces_lists_so_items_can_be_removed():
    saved = PackageDraft(
        included=["Script approval", "One revision"],
        addons=[Addon(name="Rush", price_cents=2000, unit="item")],
    )
    patched = patch_package_draft(saved, PackageDraft(included=["Script approval"], addons=[]))
    assert patched.included == ["Script approval"] and patched.addons == []


def test_patch_with_explicit_null_clears_an_optional_field():
    saved = PackageDraft(lead_time_days=14, slots_per_month=3)
    patched = patch_package_draft(saved, PackageDraft.model_validate({"lead_time_days": None}))
    assert patched.lead_time_days is None and patched.slots_per_month == 3


def test_patch_does_not_mutate_its_inputs():
    saved = PackageDraft(included=["a"])
    patch_package_draft(saved, PackageDraft(included=["b"]))
    assert saved.included == ["a"]
