from cotral_maintenance.transport import build_session


def test_referrer_is_sent_when_configured():
    assert build_session("https://example.org/").headers["Referer"] == "https://example.org/"


def test_no_referrer_by_default():
    assert "Referer" not in build_session().headers
