import io
import json
import urllib.error
from unittest import mock

import pytest

import spotify_features as sf

ID = "0mL82sxCRjrs3br407IdJh"


def test_extract_track_id():
    assert sf.extract_track_id(f"https://open.spotify.com/track/{ID}?si=abc") == ID
    assert sf.extract_track_id(f"https://open.spotify.com/intl-ko/track/{ID}") == ID
    assert sf.extract_track_id(f"spotify:track:{ID}") == ID
    assert sf.extract_track_id(ID) == ID
    for bad in ["", "hello", "https://open.spotify.com/album/" + ID, "https://example.com/track/short"]:
        assert sf.extract_track_id(bad) is None


def _http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


@pytest.mark.parametrize(
    "exc, code",
    [
        (_http_error(403), "blocked"),
        (_http_error(429), "rate_limit"),
        (_http_error(404), "not_found"),
        (_http_error(500), "network"),
        (TimeoutError(), "timeout"),
        (urllib.error.URLError(TimeoutError()), "timeout"),
        (urllib.error.URLError("dns"), "network"),
    ],
)
def test_errors_are_translated(exc, code):
    with mock.patch("urllib.request.urlopen", side_effect=exc):
        with pytest.raises(sf.LookupFailed) as e:
            sf.fetch_features(ID)
    assert e.value.code == code


def _response(payload):
    resp = mock.MagicMock()
    resp.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return resp


def test_empty_content_is_not_found():
    with mock.patch("urllib.request.urlopen", return_value=_response({"content": []})):
        with pytest.raises(sf.LookupFailed) as e:
            sf.fetch_features(ID)
    assert e.value.code == "not_found"


def test_missing_feature_is_bad_response():
    with mock.patch("urllib.request.urlopen", return_value=_response({"content": [{"energy": 0.5}]})):
        with pytest.raises(sf.LookupFailed) as e:
            sf.fetch_features(ID)
    assert e.value.code == "bad_response"


def test_user_agent_and_timeout_are_sent():
    with mock.patch("urllib.request.urlopen", side_effect=TimeoutError()) as m:
        with pytest.raises(sf.LookupFailed):
            sf.fetch_features(ID)
    req = m.call_args.args[0]
    assert req.get_header("User-agent") == sf.USER_AGENT
    assert m.call_args.kwargs["timeout"] == sf.TIMEOUT_SECONDS
