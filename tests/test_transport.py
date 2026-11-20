from cotral_maintenance.transport import build_session


def test_referrer_is_sent_when_configured():
    assert build_session("https://example.org/").headers["Referer"] == "https://example.org/"


def test_no_referrer_by_default():
    assert "Referer" not in build_session().headers


def test_only_a_refused_key_or_quota_is_fatal():
    from cotral_maintenance.errors import ApiError
    assert ApiError("HTTP_403").fatal and ApiError("REQUEST_DENIED").fatal and ApiError("HTTP_429").fatal
    assert not ApiError("HTTP_503").fatal and not ApiError("HTTP_404").fatal and not ApiError("INVALID_JSON").fatal
