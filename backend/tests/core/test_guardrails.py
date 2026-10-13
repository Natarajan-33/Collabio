from app.core.guardrails import (
    MAX_CALLS_PER_BRAND_PER_DAY,
    brand_counter_violation,
    call_allowed,
    channel_violation,
    check_counter,
    default_channel,
    floor_shortfall,
    over_ceiling_cents,
)

KW = {"ceiling_cents": 120000, "ask_cents": 100000, "brief_videos": 3, "brand_name": "Lumen Audio"}
PHONE = "+15551234567"


def test_call_cap():
    assert MAX_CALLS_PER_BRAND_PER_DAY == 20


def test_over_ceiling_first_concession_is_midpoint():
    v = check_counter(offered_price_cents=130000, offered_videos=3, concessions_made=0, **KW)
    assert (v.verdict, v.suggested_counter_price_cents) == ("over", 110000)
    assert v.talking_point == "That's above what Lumen Audio can do. Offer $1,100 instead."


def test_second_concession_moves_three_quarters():
    v = check_counter(offered_price_cents=130000, offered_videos=3, concessions_made=1, **KW)
    assert (v.verdict, v.suggested_counter_price_cents) == ("over", 115000)
    assert v.talking_point == "That's above what Lumen Audio can do. Offer $1,150 instead."


def test_within_ceiling():
    v = check_counter(offered_price_cents=120000, offered_videos=3, concessions_made=2, **KW)
    assert (v.verdict, v.suggested_counter_price_cents) == ("within", None)
    assert (
        v.talking_point
        == "That fits. Agree in principle and say Lumen Audio will confirm in writing."
    )


def test_fewer_videos_scales_ceiling():
    v = check_counter(offered_price_cents=90000, offered_videos=2, concessions_made=0, **KW)
    # the ceiling for 2 of 3 videos is 80000, so 90000 is over
    assert v.verdict == "over"
    assert v.suggested_counter_price_cents is not None
    assert 66600 <= v.suggested_counter_price_cents <= 80000
    assert v.suggested_counter_price_cents % 100 == 0


def test_fewer_videos_within_scaled_ceiling():
    v = check_counter(offered_price_cents=80000, offered_videos=2, concessions_made=0, **KW)
    assert v.verdict == "within"


def test_suggestion_never_above_ceiling():
    v = check_counter(offered_price_cents=500000, offered_videos=3, concessions_made=10, **KW)
    assert v.verdict == "over"
    assert v.suggested_counter_price_cents <= 120000


def test_channels():
    assert default_channel("phone_ok", PHONE, True) == "call"
    assert default_channel("email_first", PHONE, True) == "email"
    assert default_channel("email_only", PHONE, True) == "email"
    assert default_channel("phone_ok", None, True) == "email"
    assert default_channel("phone_ok", PHONE, False) == "email"


def test_call_allowed():
    assert call_allowed(PHONE, True)
    assert not call_allowed(PHONE, False)
    assert not call_allowed(None, True)
    assert not call_allowed("  ", True)


def test_channel_violation():
    kw = {"phone": PHONE, "phone_opt_in": True, "contact_opt_out": False}
    assert channel_violation("email", **kw) is None
    assert channel_violation("call", **kw) is None
    assert (
        channel_violation("call", phone=PHONE, phone_opt_in=False, contact_opt_out=False)
        == "No phone opt-in"
    )
    assert (
        channel_violation("email_then_call", phone=None, phone_opt_in=True, contact_opt_out=False)
        == "No phone opt-in"
    )
    assert channel_violation("email", phone=None, phone_opt_in=False, contact_opt_out=False) is None
    assert (
        channel_violation("call", phone=PHONE, phone_opt_in=False, contact_opt_out=True)
        == "Opted out of contact"
    )
    assert channel_violation("email", **{**kw, "contact_opt_out": True}) == "Opted out of contact"


def test_floor_scales_up_with_videos():
    # floor scales to 120000
    assert (
        floor_shortfall(price_cents=100000, videos=4, package_volume=2, floor_cents=60000) == 20000
    )


def test_floor_rounds_up_for_creator():
    # ceil(33333.33) = 33334
    assert floor_shortfall(price_cents=33333, videos=1, package_volume=3, floor_cents=100000) == 1


def test_floor_met_is_none():
    assert floor_shortfall(price_cents=60000, videos=2, package_volume=2, floor_cents=60000) is None


def test_brand_counter_over_ceiling_message():
    assert (
        brand_counter_violation(price_cents=130000, videos=3, brief_videos=3, ceiling_cents=120000)
        == "Above your ceiling of $1,200 for 3 videos"
    )


def test_brand_counter_scales_ceiling():
    # scaled ceiling is 80000
    assert (
        brand_counter_violation(price_cents=80000, videos=2, brief_videos=3, ceiling_cents=120000)
        is None
    )


def test_brand_counter_singular():
    assert (
        brand_counter_violation(price_cents=50000, videos=1, brief_videos=3, ceiling_cents=120000)
        == "Above your ceiling of $400 for 1 video"
    )


def test_over_ceiling_cents():
    assert (
        over_ceiling_cents(price_cents=125000, videos=3, brief_videos=3, ceiling_cents=120000)
        == 5000
    )


def test_over_ceiling_cents_within_is_none():
    assert (
        over_ceiling_cents(price_cents=120000, videos=3, brief_videos=3, ceiling_cents=120000)
        is None
    )
