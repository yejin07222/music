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


def _routes(table):
    """A urlopen stand-in answering by URL path prefix; a value that is an Exception is raised."""
    def fake(req, timeout=None):
        url = req.full_url
        for prefix, payload in table.items():
            if prefix in url:
                if isinstance(payload, Exception):
                    raise payload
                return _response(payload)
        raise AssertionError(f"unexpected url {url}")
    return fake


def _track(i, title, artist, isrc=None):
    return {"id": i, "title": title, "artist": {"name": artist}, "isrc": isrc, "preview": "p", "link": "l",
            "album": {"cover_medium": "c"}}


def test_search_online_puts_the_exact_name_artist_with_most_fans_first():
    table = {
        "/search/artist": {"data": [
            {"id": 1, "name": "Oasis", "nb_fan": 10}, {"id": 927, "name": "oasis", "nb_fan": 900000},
            {"id": 2, "name": "Oasis Jazz", "nb_fan": 9999},
        ]},
        "/artist/927/top": {"data": [_track(11, "Wonderwall", "Oasis"), _track(12, "Supersonic", "Oasis")]},
        "/search?": {"data": [_track(21, "Oasis", "Other", "ISRC21"), _track(11, "Wonderwall", "Oasis", "ISRC11")]},
    }
    with mock.patch("urllib.request.urlopen", side_effect=_routes(table)):
        songs = ol.search_online("Oasis")
    assert [(s["id"], s["isrc"]) for s in songs] == [(11, None), (12, None), (21, "ISRC21")]  # artist songs first, no repeat


def test_search_online_without_artist_match_uses_the_title_search_only():
    table = {"/search/artist": {"data": [{"id": 5, "name": "Someone", "nb_fan": 1}]},
             "/search?": {"data": [_track(1, "Go Hard", "A", "I1")]}}
    with mock.patch("urllib.request.urlopen", side_effect=_routes(table)):
        assert [s["title"] for s in ol.search_online("Go Hard")] == ["Go Hard"]


def test_search_online_uses_newest_albums_when_the_top_list_is_empty():
    table = {
        "/search/artist": {"data": [{"id": 7, "name": "MEOVV", "nb_fan": 50000}]},
        "/artist/7/top": {"data": []},
        "/artist/7/albums": {"data": [{"id": 70, "release_date": "2024-01-01", "cover_medium": "old"},
                                      {"id": 71, "release_date": "2025-06-01", "cover_medium": "new"}]},
        "/album/71/tracks": {"data": [{"id": 5, "title": "GO HARD", "artist": {"name": "MEOVV"}}]},
        "/album/70/tracks": {"data": []},
        "/search?": {"data": [_track(9, "Go Hard", "Other", "I9")]},
    }
    with mock.patch("urllib.request.urlopen", side_effect=_routes(table)):
        songs = ol.search_online("MEOVV")
    assert [(s["title"], s["cover"]) for s in songs] == [("GO HARD", "new"), ("Go Hard", "c")]


def test_search_online_survives_one_lookup_failing_but_not_both():
    ok = {"/search?": {"data": [_track(1, "A", "x", "I1")]}}
    with mock.patch("urllib.request.urlopen", side_effect=_routes({"/search/artist": _http_error(500), **ok})):
        assert [s["id"] for s in ol.search_online("q")] == [1]
    with mock.patch("urllib.request.urlopen", side_effect=_routes({"/search/artist": _http_error(429), "/search?": _http_error(500)})):
        with pytest.raises(ol.LookupFailed) as e:
            ol.search_online("q")
    assert e.value.code == "rate_limit"


def test_search_online_no_results():
    with mock.patch("urllib.request.urlopen", side_effect=_routes({"/search/artist": {"data": []}, "/search?": {"data": []}})):
        with pytest.raises(ol.LookupFailed) as e:
            ol.search_online("q")
    assert e.value.code == "no_results"


def test_resolve_isrc():
    with mock.patch("urllib.request.urlopen", return_value=_response({"id": 1, "isrc": " gbaaa1 "})):
        assert ol.resolve_isrc(1) == "GBAAA1"
    with mock.patch("urllib.request.urlopen", return_value=_response({"id": 1})):
        with pytest.raises(ol.LookupFailed) as e:
            ol.resolve_isrc(1)
    assert e.value.code == "not_found"


def test_search_online_ignores_artists_with_very_few_fans():
    table = {"/search/artist": {"data": [{"id": 5, "name": "Someone Like You", "nb_fan": 4370}]},
             "/search?": {"data": [_track(1, "Someone Like You", "Adele", "I1")]}}  # no /top route: it must not be asked
    with mock.patch("urllib.request.urlopen", side_effect=_routes(table)):
        assert [s["artist"] for s in ol.search_online("Someone Like You")] == ["Adele"]


def test_search_online_finds_a_song_from_title_plus_artist():
    table = {
        "/search/artist": {"data": [{"id": 7, "name": "MEOVV", "nb_fan": 50000}]},
        "/artist/7/top": {"data": [_track(1, "ME ME ME", "MEOVV")]},  # the hinted song is missing here
        "/artist/7/albums": {"data": [{"id": 70, "release_date": "2025-06-01"}]},
        "/album/70/tracks": {"data": [{"id": 5, "title": "GO HARD", "artist": {"name": "MEOVV"}}, _track(6, "Team", "MEOVV")]},
        "/search?": {"data": [_track(1, "ME ME ME", "MEOVV", "I1")]},
    }
    with mock.patch("urllib.request.urlopen", side_effect=_routes(table)):
        songs = ol.search_online("Go Hard MEOVV")
    assert songs[0]["title"] == "GO HARD"


def test_search_online_gives_up_on_slow_lookups_after_the_time_limit():
    import time

    def fake(req, timeout=None):
        if "/search/artist" in req.full_url:
            time.sleep(1.0)
            return _response({"data": []})
        return _response({"data": [_track(1, "A", "x", "I1")]})

    start = time.monotonic()
    with mock.patch.object(ol, "SEARCH_TIMEOUT_SECONDS", 0.2), mock.patch("urllib.request.urlopen", side_effect=fake):
        songs = ol.search_online("q")
    assert [s["id"] for s in songs] == [1] and time.monotonic() - start < 0.8
