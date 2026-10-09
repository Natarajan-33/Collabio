import hashlib

from app.core.package_text import creator_embedding_document, package_one_liner, text_hash
from app.schemas.packages import Addon
from tests.core.factories import make_pkg


def test_one_liner_contract_with_extra_video():
    pkg = make_pkg(
        volume_count=2,
        volume_basis="per_contract",
        base_price_cents=100000,
        addons=[Addon(name="Extra video", price_cents=40000, unit="video")],
    )
    assert package_one_liner(pkg) == "2 videos/contract · $1,000 · +1 video $400"


def test_one_liner_weekly_no_addons():
    pkg = make_pkg(volume_count=1, volume_basis="per_week", base_price_cents=150000, addons=[])
    assert package_one_liner(pkg) == "1 video/week · $1,500"


def test_text_tolerates_unset_lead_time_and_slots():
    pkg = make_pkg(lead_time_days=None, slots_per_month=None)
    assert package_one_liner(pkg) == "2 videos/contract · $1,000"
    _, text = creator_embedding_document("Maya Chen", "Gadgets", ["consumer_tech"], [pkg])
    assert "2 videos/contract · $1,000" in text


def test_one_liner_ignores_item_addons():
    pkg = make_pkg(addons=[Addon(name="Rush delivery", price_cents=20000, unit="item")])
    assert package_one_liner(pkg) == "2 videos/contract · $1,000"


def test_embedding_document_mentions_niche_labels_and_one_liners():
    title, text = creator_embedding_document(
        "Maya Chen", "Honest gadget reviews", ["consumer_tech"], [make_pkg()]
    )
    assert title == "Maya Chen"
    assert "consumer tech" in text and "2 videos/contract" in text


def test_embedding_document_includes_bio_every_niche_and_every_package():
    _, text = creator_embedding_document(
        "Sam Lee",
        "Desk setups and SaaS walkthroughs",
        ["consumer_tech", "b2b_saas"],
        [
            make_pkg(name="Launch Duo", content_type="short_video"),
            make_pkg(
                name="Deep Dive", content_type="long_video", volume_count=1, base_price_cents=250000
            ),
        ],
    )
    assert "Desk setups and SaaS walkthroughs" in text
    assert "consumer tech" in text and "b2b saas" in text
    assert "Launch Duo" in text and "short video" in text
    assert "Deep Dive" in text and "long video" in text and "1 video/contract · $2,500" in text


def test_text_hash_is_sha256_of_title_newline_text():
    expected = hashlib.sha256(b"Maya Chen\nHonest gadget reviews").hexdigest()
    assert text_hash("Maya Chen", "Honest gadget reviews") == expected


def test_text_hash_changes_when_text_changes():
    assert text_hash("Maya Chen", "a") != text_hash("Maya Chen", "b")
