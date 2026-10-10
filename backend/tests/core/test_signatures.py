"""ElevenLabs webhook signatures: `t=<unix>,v0=<hex>` over `<t>.<raw body>`."""

import hashlib
import hmac

from app.core.signatures import sign_elevenlabs_payload, verify_elevenlabs_signature

SECRET = "hook-secret"
RAW = b'{"type": "post_call_transcription"}'
NOW = 1_800_000_000.0


def test_signature_valid():
    header = sign_elevenlabs_payload(RAW, SECRET, int(NOW))
    assert header.startswith(f"t={int(NOW)},v0=")
    assert verify_elevenlabs_signature(RAW, header, SECRET, now=NOW)


def test_signature_is_hmac_sha256_over_timestamp_dot_body():
    expected = hmac.new(SECRET.encode(), f"{int(NOW)}.".encode() + RAW, hashlib.sha256).hexdigest()
    assert sign_elevenlabs_payload(RAW, SECRET, int(NOW)) == f"t={int(NOW)},v0={expected}"


def test_tampered_body_rejected():
    header = sign_elevenlabs_payload(RAW, SECRET, int(NOW))
    assert not verify_elevenlabs_signature(RAW + b" ", header, SECRET, now=NOW)


def test_wrong_secret_rejected():
    header = sign_elevenlabs_payload(RAW, "other-secret", int(NOW))
    assert not verify_elevenlabs_signature(RAW, header, SECRET, now=NOW)


def test_empty_secret_rejected():
    header = sign_elevenlabs_payload(RAW, "", int(NOW))
    assert not verify_elevenlabs_signature(RAW, header, "", now=NOW)


def test_stale_timestamp_rejected():
    header = sign_elevenlabs_payload(RAW, SECRET, int(NOW) - 1801)
    assert not verify_elevenlabs_signature(RAW, header, SECRET, now=NOW)
    fresh = sign_elevenlabs_payload(RAW, SECRET, int(NOW) - 1800)
    assert verify_elevenlabs_signature(RAW, fresh, SECRET, now=NOW)


def test_far_future_timestamp_rejected():
    header = sign_elevenlabs_payload(RAW, SECRET, int(NOW) + 3600)
    assert not verify_elevenlabs_signature(RAW, header, SECRET, now=NOW)


def test_missing_or_malformed_header_rejected():
    good = sign_elevenlabs_payload(RAW, SECRET, int(NOW))
    digest = good.split("v0=")[1]
    for header in (
        None,
        "",
        "garbage",
        f"v0={digest}",
        f"t={int(NOW)}",
        f"t=soon,v0={digest}",
        f"t={int(NOW)},v0=",
        f"t={int(NOW)},v1={digest}",
    ):
        assert not verify_elevenlabs_signature(RAW, header, SECRET, now=NOW), header


def test_non_utf8_body_rejected_not_raised():
    header = sign_elevenlabs_payload(RAW, SECRET, int(NOW))
    assert not verify_elevenlabs_signature(b"\xff\xfe", header, SECRET, now=NOW)
