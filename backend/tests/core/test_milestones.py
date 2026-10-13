from datetime import date

from app.core.milestones import split_even, validate_milestones
from app.schemas.deals import AgreedTerms, MilestoneDraft

AGREED = AgreedTerms(
    videos=3, format="short_video", price_cents=110000, go_live_by=date(2026, 11, 30)
)


def ms(rows):
    return [
        MilestoneDraft(seq=seq, title=f"Video {seq}", amount_cents=amount, due_date=due)
        for seq, amount, due in rows
    ]


GOOD = [
    (1, 50000, date(2026, 11, 30)),
    (2, 30000, date(2026, 12, 7)),
    (3, 30000, date(2026, 12, 14)),
]


def test_split_even_puts_remainder_last():
    out = split_even(100000, 3, date(2026, 11, 30))
    assert [m.amount_cents for m in out] == [33333, 33333, 33334]
    assert [m.title for m in out] == ["Video 1", "Video 2", "Video 3"]
    assert {m.due_date for m in out} == {date(2026, 11, 30)}
    assert [m.seq for m in out] == [1, 2, 3]


def test_split_even_single_video_takes_it_all():
    out = split_even(55000, 1, date(2026, 11, 30))
    assert [(m.seq, m.amount_cents) for m in out] == [(1, 55000)]


def test_valid_edit_passes():
    assert validate_milestones(AGREED, ms(GOOD)) == []


def test_split_even_validates_against_its_own_terms():
    assert validate_milestones(AGREED, split_even(110000, 3, date(2026, 11, 30))) == []


def test_wrong_count():
    assert validate_milestones(AGREED, ms(GOOD[:2])) == ["Expected 3 milestones, one per video"]


def test_wrong_sum():
    rows = [(1, 40000, date(2026, 11, 30)), GOOD[1], GOOD[2]]
    assert validate_milestones(AGREED, ms(rows)) == [
        "Payments add up to $1,000, not the agreed $1,100"
    ]


def test_earlier_date_rejected():
    rows = [GOOD[0], (2, 30000, date(2026, 11, 29)), GOOD[2]]
    assert validate_milestones(AGREED, ms(rows)) == [
        "Video 2 is due before the agreed go-live date Nov 30, 2026"
    ]


def test_date_message_uses_seq_not_title():
    drafts = ms(GOOD)
    drafts[1] = MilestoneDraft(
        seq=2, title="Intro cut", amount_cents=30000, due_date=date(2026, 11, 1)
    )
    assert validate_milestones(AGREED, drafts) == [
        "Video 2 is due before the agreed go-live date Nov 30, 2026"
    ]


def test_tiny_amount():
    rows = [GOOD[0], (2, 99, date(2026, 12, 7)), GOOD[2]]
    assert "Each payment must be at least $1" in validate_milestones(AGREED, ms(rows))


def test_seq_must_run():
    rows = [GOOD[0], GOOD[1], (4, 30000, date(2026, 12, 14))]
    assert "Milestone numbers must run 1 to 3" in validate_milestones(AGREED, ms(rows))


def test_errors_accumulate():
    rows = [(1, 40000, date(2026, 11, 29)), GOOD[1], GOOD[2]]
    assert validate_milestones(AGREED, ms(rows)) == [
        "Payments add up to $1,000, not the agreed $1,100",
        "Video 1 is due before the agreed go-live date Nov 30, 2026",
    ]


def test_blank_or_long_title_rejected():
    expected = ["Every milestone needs a title of at most 80 characters"]
    for title in ("", "x" * 81):
        drafts = ms(GOOD)
        drafts[0] = MilestoneDraft.model_construct(
            seq=1, title=title, amount_cents=50000, due_date=date(2026, 11, 30)
        )
        assert validate_milestones(AGREED, drafts) == expected
