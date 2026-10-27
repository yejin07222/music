import io
import json
import urllib.error
from unittest import mock

import pytest

import online_lookup as ol


def _response(payload):
    resp = mock.MagicMock()
    resp.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return resp


def _http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


def _item(title, artist, isrc):
    return {"title": title, "artist": {"name": artist}, "isrc": isrc}


def test_search_skips_missing_isrc_and_repeats_and_caps_at_five():
    items = [_item("a", "x", ""), _item("b", "x", None), {"title": "no artist"}]
    items += [_item(f"t{i}", "x", f"ISRC{i // 2}") for i in range(20)]  # each ISRC twice
    with mock.patch("urllib.request.urlopen", return_value=_response({"data": items})):
        songs = ol.search_songs("q")
    assert [s["isrc"] for s in songs] == [f"ISRC{i}" for i in range(5)]
    assert songs[0] == {"title": "t0", "artist": "x", "isrc": "ISRC0", "preview": None, "cover": None, "link": None}


def test_search_no_usable_results():
    with mock.patch("urllib.request.urlopen", return_value=_response({"data": [_item("a", "x", "")]})):
        with pytest.raises(ol.LookupFailed) as e:
            ol.search_songs("q")
    assert e.value.code == "no_results"


@pytest.mark.parametrize(
    "payload, code",
    [({"error": {"code": 4}}, "rate_limit"), ({"error": {"code": 800}}, "bad_response"), ([], "bad_response")],
)
def test_search_deezer_error_bodies(payload, code):
    with mock.patch("urllib.request.urlopen", return_value=_response(payload)):
        with pytest.raises(ol.LookupFailed) as e:
            ol.search_songs("q")
    assert e.value.code == code


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
@pytest.mark.parametrize("call", [ol.search_songs, ol.fetch_features])
def test_http_errors_are_translated(call, exc, code):
    with mock.patch("urllib.request.urlopen", side_effect=exc):
        with pytest.raises(ol.LookupFailed) as e:
            call("x")
    assert e.value.code == code


def test_fetch_features_ok():
    row = {f: 0.5 for f in ol.FEATURES} | {"href": "https://open.spotify.com/track/abc123"}
    with mock.patch("urllib.request.urlopen", return_value=_response({"content": [row]})):
        features, spotify_id = ol.fetch_features("USUG12106692")
    assert set(features) == set(ol.FEATURES) and spotify_id == "abc123"


def test_fetch_features_empty_and_malformed():
    for payload, code in [({"content": []}, "not_found"), ({"content": [{"energy": 0.5}]}, "bad_response")]:
        with mock.patch("urllib.request.urlopen", return_value=_response(payload)):
            with pytest.raises(ol.LookupFailed) as e:
                ol.fetch_features("X")
        assert e.value.code == code


def test_user_agent_and_timeout_are_sent():
    with mock.patch("urllib.request.urlopen", side_effect=TimeoutError()) as m:
        with pytest.raises(ol.LookupFailed):
            ol.search_songs("q")
    assert m.call_args.args[0].get_header("User-agent") == ol.USER_AGENT
    assert m.call_args.kwargs["timeout"] == ol.TIMEOUT_SECONDS


def test_search_keeps_preview_and_cover():
    item = {"title": "t", "artist": {"name": "a"}, "isrc": "x1", "preview": "https://cdnt-preview.dzcdn.net/p.mp3",
            "album": {"cover_medium": "https://cdn-images.dzcdn.net/c.jpg"}}
    bare = {"title": "u", "artist": {"name": "b"}, "isrc": "x2"}  # no preview, no album
    with mock.patch("urllib.request.urlopen", return_value=_response({"data": [item, bare]})):
        songs = ol.search_songs("q")
    assert songs[0]["preview"].endswith("p.mp3") and songs[0]["cover"].endswith("c.jpg")
    assert songs[1]["preview"] is None and songs[1]["cover"] is None
