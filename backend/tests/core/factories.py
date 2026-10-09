from app.schemas.packages import PackageTerms


def make_pkg(**overrides) -> PackageTerms:
    """A valid package: 2 short videos per contract, consumer tech, $1,000, phone OK."""
    fields = {
        "name": "Launch Duo",
        "content_type": "short_video",
        "niche": "consumer_tech",
        "volume_count": 2,
        "volume_basis": "per_contract",
        "base_price_cents": 100000,
        "lead_time_days": 14,
        "preferred_channel": "phone_ok",
    }
    fields.update(overrides)
    return PackageTerms(**fields)
