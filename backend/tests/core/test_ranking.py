from datetime import date, timedelta
from uuid import UUID

from app.core.ranking import RankInput, rank_threads
from app.schemas.negotiation import NegotiationTerms

GO_LIVE = date(2026, 11, 14)
PRIYA = UUID("00000000-0000-0000-0000-00000000000a")
ARJUN = UUID("00000000-0000-0000-0000-00000000000b")
MEI = UUID("00000000-0000-0000-0000-00000000000c")


def t(
    id_,
    price,
    videos=3,
    go_live=GO_LIVE,
    status="countered",
    source="creator",
    eng=4.0,
    sim=0.5,
):
    return RankInput(
        id_,
        status,
        NegotiationTerms(
            videos=videos,
            price_cents=price,
            go_live_by=go_live,
            stance="counter",
            source="call",
            confidence=0.9,
        ),
        source,
        eng,
        sim,
    )


def rank(items, ceiling=120000):
    return rank_threads(items, ceiling_cents=ceiling, brief_videos=3, go_live_by=GO_LIVE)


def test_spec_demo_priya_beats_arjun_on_price():
    # Priya: $1,100 for 3 (367/video), a week late; Arjun: $1,200 for 3 (400/video), on time
    r = rank(
        [t(PRIYA, 110000, go_live=GO_LIVE + timedelta(days=7)), t(ARJUN, 120000)],
    )
    assert r[PRIYA].eligible and r[PRIYA].ineligible_reason is None
    assert r[PRIYA].rank == 1 and r[PRIYA].per_video_cents == 36667
    assert r[PRIYA].score == 0.875
    assert "Lowest $/video" in r[PRIYA].reasons
    assert "Meets go-live date" not in r[PRIYA].reasons
    assert r[ARJUN].rank == 2 and r[ARJUN].score == 0.5
    assert r[ARJUN].per_video_cents == 40000
    assert "Meets go-live date" in r[ARJUN].reasons
    assert "Lowest $/video" not in r[ARJUN].reasons


def test_over_budget_ineligible():
    r = rank([t(PRIYA, 130000)])
    b = r[PRIYA]
    assert not b.eligible and b.ineligible_reason == "Over budget"
    assert b.rank is None and b.score is None and b.per_video_cents is None
    assert b.reasons == []
    assert b.thread_id == PRIYA


def test_fewer_videos_ineligible():
    r = rank([t(PRIYA, 90000, videos=2)])
    assert not r[PRIYA].eligible
    assert r[PRIYA].ineligible_reason == "Fewer videos than asked"
    assert r[PRIYA].rank is None


def test_over_budget_checked_before_fewer_videos():
    r = rank([t(PRIYA, 130000, videos=2)])
    assert r[PRIYA].ineligible_reason == "Over budget"


def test_brand_terms_or_open_status_ineligible():
    r = rank(
        [
            t(PRIYA, 100000, source="brand"),
            t(ARJUN, 100000, status="awaiting_reply"),
            RankInput(MEI, "countered", None, None, None, None),
        ]
    )
    for tid in (PRIYA, ARJUN, MEI):
        assert not r[tid].eligible
        assert r[tid].ineligible_reason == "No creator terms yet"
        assert r[tid].rank is None


def test_terms_missing_price_or_videos_ineligible():
    no_price = RankInput(
        PRIYA,
        "countered",
        NegotiationTerms(videos=3, stance="question", source="email", confidence=0.5),
        "creator",
        None,
        None,
    )
    no_videos = RankInput(
        ARJUN,
        "accepted",
        NegotiationTerms(price_cents=1000, stance="accept", source="email", confidence=0.5),
        "creator",
        None,
        None,
    )
    r = rank([no_price, no_videos])
    assert r[PRIYA].ineligible_reason == "No creator terms yet"
    assert r[ARJUN].ineligible_reason == "No creator terms yet"


def test_accepted_status_is_eligible():
    r = rank([t(PRIYA, 100000, status="accepted")])
    assert r[PRIYA].eligible


def test_single_eligible_scores_full_value():
    r = rank([t(PRIYA, 100000)])
    assert r[PRIYA].rank == 1 and r[PRIYA].score == 1.0
    assert r[PRIYA].reasons == ["Lowest $/video", "Meets go-live date"]


def test_single_eligible_late_loses_timeline_only():
    r = rank([t(PRIYA, 100000, go_live=GO_LIVE + timedelta(days=14))])
    assert r[PRIYA].score == 0.75
    assert "Meets go-live date" not in r[PRIYA].reasons


def test_timeline_floors_at_zero_and_unset_go_live_is_full():
    r = rank(
        [
            t(PRIYA, 100000, go_live=GO_LIVE + timedelta(days=40)),
            t(ARJUN, 100000, go_live=None),
            t(MEI, 100000, go_live=GO_LIVE - timedelta(days=3)),
        ]
    )
    assert r[PRIYA].score == 0.75
    assert r[ARJUN].score == 1.0 and r[MEI].score == 1.0
    assert "Meets go-live date" in r[ARJUN].reasons


def test_ties_broken_by_engagement():
    # Priya: cheaper, a fortnight late, low engagement -> 0.5 * 1 + 0 + 0
    # Arjun: dearer, on time, high engagement -> 0 + 0.25 + 0.25
    r = rank(
        [
            t(PRIYA, 100000, go_live=GO_LIVE + timedelta(days=14), eng=1.0, sim=None),
            t(ARJUN, 120000, eng=9.0, sim=None),
        ]
    )
    assert r[PRIYA].score == r[ARJUN].score == 0.5
    assert r[ARJUN].rank == 1 and r[PRIYA].rank == 2


def test_full_tie_falls_back_to_thread_id():
    r = rank([t(ARJUN, 100000), t(PRIYA, 100000)])
    assert r[PRIYA].rank == 1 and r[ARJUN].rank == 2


def test_audience_uses_available_components_min_max():
    r = rank(
        [
            t(PRIYA, 100000, eng=2.0, sim=0.2),
            t(ARJUN, 100000, eng=6.0, sim=0.8),
        ]
    )
    # Arjun: audience 1.0; Priya: 0.0 -> scores 0.75 and 1.0
    assert r[ARJUN].score == 1.0 and r[PRIYA].score == 0.75
    assert "Strongest audience match" in r[ARJUN].reasons
    assert "Strongest audience match" not in r[PRIYA].reasons


def test_audience_defaults_to_half_when_no_components():
    r = rank([t(PRIYA, 100000, eng=None, sim=None)])
    assert r[PRIYA].score == 0.875


def test_missing_component_averages_only_present_ones():
    # Priya has both (eng 2, sim 0.2); Arjun has only sim (0.8); Mei has only eng (6)
    r = rank(
        [
            t(PRIYA, 100000, eng=2.0, sim=0.2),
            t(ARJUN, 100000, eng=None, sim=0.8),
            t(MEI, 100000, eng=6.0, sim=None),
        ]
    )
    # sim normalised over {0.2, 0.8}: Priya 0, Arjun 1; eng over {2, 6}: Priya 0, Mei 1
    # audience: Priya mean(0,0)=0, Arjun 1, Mei 1
    assert r[PRIYA].score == 0.75
    assert r[ARJUN].score == 1.0 and r[MEI].score == 1.0


def test_ineligible_do_not_influence_normalisation():
    r = rank(
        [
            t(PRIYA, 100000),
            t(ARJUN, 110000),
            t(MEI, 130000),  # over budget, would be max pv
        ]
    )
    assert r[ARJUN].score < r[PRIYA].score
    assert r[ARJUN].score == 0.5  # value 0 (max among eligible) + timeline 0.25 + audience 0.25


def test_every_input_gets_an_entry_and_ranks_are_dense():
    r = rank([t(PRIYA, 100000), t(ARJUN, 110000), t(MEI, 130000)])
    assert set(r) == {PRIYA, ARJUN, MEI}
    assert sorted(b.rank for b in r.values() if b.rank) == [1, 2]
