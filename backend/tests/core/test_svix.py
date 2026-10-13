from datetime import UTC, datetime, timedelta

from app.core.svix import verify_svix

# Svix published vector (https://docs.svix.com/receiving/verifying-payloads/how-manual).
SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
MSG_ID, TS = "msg_p5jXN8AQM9LWM0D4loKWxJek", "1614265330"
BODY = b'{"test": 2432232314}'
SIG = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="
NOW = datetime.fromtimestamp(1614265330, UTC)


def verify(**over):
    kw = {
        "msg_id": MSG_ID,
        "timestamp": TS,
        "signature_header": SIG,
        "body": BODY,
        "now": NOW,
    } | over
    return verify_svix(SECRET, **kw)


def test_svix_vector_valid():
    assert verify()


def test_svix_any_of_several():
    assert verify(signature_header="v1,bogus " + SIG)
    assert verify(signature_header=SIG + " v1,bogus")


def test_svix_wrong_secret():
    assert not verify_svix(
        "whsec_" + "AAAA" * 8,
        msg_id=MSG_ID,
        timestamp=TS,
        signature_header=SIG,
        body=BODY,
        now=NOW,
    )


def test_svix_tampered_body():
    assert not verify(body=BODY + b" ")


def test_svix_other_message_id():
    assert not verify(msg_id="msg_other")


def test_svix_expired():
    assert not verify(now=NOW + timedelta(seconds=301))
    assert not verify(now=NOW - timedelta(seconds=301))


def test_svix_inside_tolerance():
    assert verify(now=NOW + timedelta(seconds=300))
    assert verify(now=NOW - timedelta(seconds=300))


def test_svix_malformed():
    assert not verify(signature_header="garbage")
    assert not verify(timestamp="abc")
    assert not verify(signature_header="")
    assert not verify(signature_header="v2," + SIG[3:])
    assert not verify_svix(
        "whsec_not base64!",
        msg_id=MSG_ID,
        timestamp=TS,
        signature_header=SIG,
        body=BODY,
        now=NOW,
    )
