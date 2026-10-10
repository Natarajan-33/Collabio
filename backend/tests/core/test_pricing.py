from app.core.pricing import extra_video_addon, per_video_cents
from app.schemas.packages import Addon
from tests.core.factories import make_pkg


def test_per_video_cents():
    assert per_video_cents(make_pkg(volume_count=3, base_price_cents=100000)) == 33333


def test_per_video_cents_even_split():
    assert per_video_cents(make_pkg(volume_count=2, base_price_cents=100000)) == 50000


def test_extra_video_addon_is_first_video_unit_addon():
    rush = Addon(name="Rush delivery", price_cents=20000, unit="item")
    extra = Addon(name="Extra video", price_cents=40000, unit="video")
    cutdown = Addon(name="Cutdown video", price_cents=15000, unit="video")
    assert extra_video_addon(make_pkg(addons=[rush, extra, cutdown])) == extra


def test_extra_video_addon_none_without_video_addons():
    rush = Addon(name="Rush delivery", price_cents=20000, unit="item")
    assert extra_video_addon(make_pkg(addons=[rush])) is None
    assert extra_video_addon(make_pkg(addons=[])) is None
