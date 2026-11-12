"""Final review #3: auto-pay is judged on every submission whose views the amount uses."""

from uuid import uuid4

from app.modules.money.service import settle_decision


def sub(views, confidence="high", claimed=None, status="verified", brief=True, disclosure=True):
    return {
        "id": uuid4(),
        "status": status,
        "views": views,
        "view_confidence": confidence,
        "claimed_views": views if claimed is None else claimed,
        "brief_ok": brief,
        "disclosure_ok": disclosure,
    }


def test_clean_submission_alone_auto_pays():
    s = sub(312_000)
    assert settle_decision(40_000, 50_000, s, [s]) == "auto"


def test_low_confidence_best_read_from_an_earlier_submission_needs_approval():
    earlier = sub(1_240_000, confidence="low")
    clean = sub(312_000)
    assert settle_decision(40_000, 50_000, clean, [earlier, clean]) == "approval"


def test_earlier_clean_best_read_still_auto_pays():
    earlier = sub(812_400, claimed=812_000)
    clean = sub(312_000)
    assert settle_decision(40_000, 50_000, clean, [earlier, clean]) == "auto"


def test_unverified_submissions_do_not_count():
    rejected = sub(2_000_000, confidence="low", status="needs_changes")
    clean = sub(312_000)
    assert settle_decision(40_000, 50_000, clean, [rejected, clean]) == "auto"
