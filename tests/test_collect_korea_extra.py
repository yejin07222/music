import csv
import importlib.util
import io
import json
import urllib.error
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from recommender import STYLE_FAMILIES

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "collect_korea_extra.py"
spec = importlib.util.spec_from_file_location("collect_korea_extra", SCRIPT)
cke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cke)

ALLOWED_GENRES = {"rock", "alt-rock", "emo", "indie", "indie-pop", "punk", "punk-rock", "metal", "heavy-metal", "hip-hop", "r-n-b",
                  "soul", "funk", "ballad", "folk", "singer-songwriter", "acoustic", "country", "pop", "k-pop", "dance",
                  "electronic", "edm", "house", "jazz", "blues"}


@pytest.fixture(autouse=True)
def no_waiting():
    """No sleeping between requests or retries in the tests."""
    zero = cke.Limiter(0)
    with mock.patch.object(cke, "MB_LIMIT", zero), mock.patch.object(cke, "DEEZER_LIMIT", zero), \
            mock.patch.object(cke, "RECCO_LIMIT", zero), mock.patch.object(cke.time, "sleep"):
        yield


# ------------------------------------------------------------------ pure helpers
def test_map_genres_style_first_mapped_tags_next_unique_and_capped():
    assert cke.map_genres(["indie", "rock"], ["indie rock", "folk", "korean", "k-pop"]) == ["indie", "rock", "folk", "k-pop"]
    assert cke.map_genres(["hip hop"], ["hip-hop", "rap", "r&b"]) == ["hip-hop", "r-n-b"]
    assert cke.map_genres([], [], ["korean indie", "한국 힙합"]) == ["indie", "hip-hop"]
    assert cke.map_genres(["ballad"], []) == ["ballad"] and cke.map_genres([], []) == []
    many = cke.map_genres(["rock"], ["pop", "k-pop", "dance", "electronic", "jazz", "blues", "house", "edm"])
    assert len(many) == cke.MAX_GENRES and many[0] == "rock"


def test_every_style_the_script_writes_is_known_and_recognized_by_the_style_bonus():
    for tags in cke.TAG_MAP.values():
        assert set(tags) <= ALLOWED_GENRES
    assert set(cke.SEARCH_TAG_STYLE.values()) <= ALLOWED_GENRES and set(cke.PLAYLIST_STYLE.values()) <= ALLOWED_GENRES
    every_style_tag = set(cke.SEARCH_TAG_STYLE.values())
    recognized = set().union(*STYLE_FAMILIES.values())
    assert every_style_tag <= recognized  # rock, hip-hop, r-n-b, folk, ballad, indie all count for the style bonus
    assert set(cke.PLAYLIST_STYLE.values()) <= recognized


def test_title_key_collapses_versions_of_one_song():
    assert cke.title_key("Song - Remastered 2011") == cke.title_key("Song") == "song"
    assert cke.title_key("Song (Live) [Deluxe]") == "song"
    assert cke.title_key("스물다섯, 스물하나") == "스물다섯 스물하나" and cke.title_key("") == ""
    assert cke.title_key("Hello World") != cke.title_key("Hello")


def test_instrumental_versions_are_recognized_but_real_titles_are_not():
    for t in ("Song (Inst.)", "Song - Instrumental", "Song (instrumental)", "Karaoke Song", "Song (MR)", "Song - MR"):
        assert cke.is_instrumental_title(t), t
    for t in ("Mr. Lonely", "Mister", "Instinct", "Insta Love", "Misery"):
        assert not cke.is_instrumental_title(t), t


def test_choose_albums_prefers_albums_then_popular_one_per_title():
    albums = [{"id": 1, "title": "Hit Single", "record_type": "single", "fans": 900, "release_date": "2021-01-01"},
              {"id": 2, "title": "Big Album", "record_type": "album", "fans": 50, "release_date": "2019-01-01"},
              {"id": 3, "title": "Big Album", "record_type": "album", "fans": 40, "release_date": "2020-01-01"},  # same title
              {"id": 4, "title": "Small Album", "record_type": "album", "fans": 10, "release_date": "2018-01-01"},
              {"id": 5, "title": "An EP", "record_type": "ep", "fans": 5, "release_date": "2022-01-01"},
              {"id": 6, "title": "Compilation", "record_type": "compile", "fans": 999, "release_date": "2022-01-01"}]
    assert [a["id"] for a in cke.choose_albums(albums, 4)] == [2, 4, 5, 1]
    assert [a["id"] for a in cke.choose_albums(albums, 2)] == [2, 4] and cke.choose_albums([], 5) == []


def test_safe_cell_protects_spreadsheet_formulas():
    assert cke.safe_cell("=LOVE") == "'=LOVE" and cke.safe_cell("-x") == "'-x" and cke.safe_cell("+1") == "'+1"
    assert cke.safe_cell("@a") == "'@a" and cke.safe_cell("Normal") == "Normal" and cke.safe_cell(None) == ""


def test_kr_isrc_share():
    assert cke.kr_isrc_share(["KRA123", "KRB456", "USX789", "kr0001"]) == 0.75 and cke.kr_isrc_share([]) == 0.0
    assert cke.kr_isrc_share(x for x in ["QZ1", "GB2"]) == 0.0 and cke.kr_isrc_share(["KR1", None]) == 0.5


def test_has_all_features_rejects_nulls_and_missing_numbers():
    ok = {k: 0.5 for k in cke.FEATURES}
    assert cke.has_all_features(ok) and cke.has_all_features({**ok, "tempo": 0})
    assert not cke.has_all_features({**ok, "energy": None}) and not cke.has_all_features({k: None for k in cke.FEATURES})
    assert not cke.has_all_features({**ok, "valence": "0.5"}) and not cke.has_all_features({**ok, "valence": True})
    assert not cke.has_all_features({k: 0.5 for k in cke.FEATURES[:-1]}) and not cke.has_all_features(None) and not cke.has_all_features(False)


def test_cache_persists_between_runs(tmp_path):
    c = cke.Cache(tmp_path, "x")
    assert "a" not in c and c.get("a") is None
    c.put("a", [1, "한글"], save_every=1)
    assert cke.Cache(tmp_path, "x").get("a") == [1, "한글"] and "a" in cke.Cache(tmp_path, "x")
    c.put("b", False, save_every=100)  # not saved yet...
    assert "b" not in cke.Cache(tmp_path, "x")
    c.save()
    assert "b" in cke.Cache(tmp_path, "x") and cke.Cache(tmp_path, "x").get("b") is False


# ------------------------------------------------------------------ HTTP
def _resp(payload):
    r = mock.MagicMock()
    r.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return r


def _http(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


def test_get_json_retries_backs_off_and_gives_up():
    with mock.patch("urllib.request.urlopen", side_effect=[_http(503), _http(429), _resp({"ok": 1})]) as m:
        assert cke.get_json("https://x", cke.Limiter(0)) == {"ok": 1} and m.call_count == 3
    with mock.patch("urllib.request.urlopen", side_effect=[_resp({"error": {"code": 4}}), _resp({"data": []})]):
        assert cke.get_json("https://x", cke.Limiter(0)) == {"data": []}  # Deezer quota: wait and retry
    with mock.patch("urllib.request.urlopen", return_value=_resp({"error": {"code": 800}})):
        assert cke.get_json("https://x", cke.Limiter(0)) is None  # other Deezer errors: no retry
    with mock.patch("urllib.request.urlopen", side_effect=_http(404)) as m:
        assert cke.get_json("https://x", cke.Limiter(0)) is None and m.call_count == 1
    with mock.patch("urllib.request.urlopen", side_effect=TimeoutError()) as m:
        assert cke.get_json("https://x", cke.Limiter(0), retries=3) is None and m.call_count == 3


def test_requests_send_the_user_agent():
    with mock.patch("urllib.request.urlopen", return_value=_resp({})) as m:
        cke.get_json("https://musicbrainz.org/x", cke.Limiter(0))
    ua = m.call_args.args[0].get_header("User-agent")
    assert ua == cke.USER_AGENT and "MoodMatchSchoolProject" in ua and "@" not in ua  # a project URL, no personal email


def test_limiter_spaces_requests():
    lim, t = cke.Limiter(0.5), [100.0]
    with mock.patch.object(cke.time, "monotonic", side_effect=lambda: t[0]), mock.patch.object(cke.time, "sleep", side_effect=lambda s: t.__setitem__(0, t[0] + s)) as sl:
        lim.wait(); lim.wait()
    assert sl.call_count == 1 and sl.call_args.args[0] == pytest.approx(0.5)


# ------------------------------------------------------------------ the stages (get_json mocked)
def test_mb_artists_reads_every_page_and_keeps_korean_ones(tmp_path):
    pages = [{"count": 150, "artists": [{"id": f"a{i}", "name": f"N{i}", "country": "KR"} for i in range(100)]},
             {"count": 150, "artists": [{"id": "x", "name": "Foreign", "country": "JP"}] + [{"id": f"b{i}", "name": f"M{i}", "country": "KR"} for i in range(49)]}]
    cache = cke.Cache(tmp_path, "mb")
    with mock.patch.object(cke, "get_json", side_effect=pages) as m:
        out = cke.mb_artists("rock", cache)
    assert len(out) == 149 and m.call_count == 2 and "offset=100" in m.call_args_list[1].args[0]
    assert "country%3AKR" in m.call_args_list[0].args[0] and "tag%3A%22rock%22" in m.call_args_list[0].args[0]
    with mock.patch.object(cke, "get_json") as m:
        assert len(cke.mb_artists("rock", cache)) == 149 and not m.called  # cached
    with mock.patch.object(cke, "get_json", return_value=None):  # a failing service ends the paging
        assert cke.mb_artists("folk", cke.Cache(tmp_path, "mb2")) == []


def test_match_deezer_artist_exact_name_or_alias_most_fans_and_how_many_share_the_name(tmp_path):
    data = {"data": [{"id": 1, "name": "Crush", "nb_fan": 10}, {"id": 2, "name": "crush", "nb_fan": 500}, {"id": 3, "name": "Crush Boys", "nb_fan": 9999}]}
    cache = cke.Cache(tmp_path, "d")
    with mock.patch.object(cke, "get_json", return_value=data):
        best = cke.match_deezer_artist("Crush", [], cache, "k1")
        assert best["id"] == 2 and best["n_exact"] == 2  # exact name only, the bigger one; two artists share the name
        assert [d["id"] for d in cke.deezer_exact_matches("Crush", [], cache, "k1")] == [2, 1]  # most fans first
        alias = cke.match_deezer_artist("크러쉬", ["Crush Boys"], cache, "k2")
        assert alias["id"] == 3 and alias["n_exact"] == 1  # alias
        assert cke.match_deezer_artist("Nobody", [], cache, "k3") is None and cke.deezer_exact_matches("Nobody", [], cache, "k3") == []
    assert "k3" in cache  # the failure is remembered too


def test_mb_country(tmp_path):
    cache = cke.Cache(tmp_path, "c")
    def lookup(name, artists):
        with mock.patch.object(cke, "get_json", return_value={"artists": artists}):
            return cke.mb_country(name, cache)
    assert lookup("Colde", [{"name": "Colde", "country": "KR"}]) == "KR"
    assert lookup("Zia", [{"name": "Zia", "country": None, "area": {"name": "South Korea"}}]) == "KR"
    assert lookup("Etta Bond", [{"name": "Etta Bond", "country": "GB"}]) == "GB"
    assert lookup("Marlena", [{"name": "Other Name", "country": "KR"}]) == "unknown"  # a different artist
    assert lookup("Alias", [{"name": "Real", "country": "KR", "aliases": [{"name": "alias"}]}]) == "KR"
    assert lookup("Nobody", []) == "unknown"
    with mock.patch.object(cke, "get_json") as m:
        assert cke.mb_country("Colde", cache) == "KR" and not m.called
    with mock.patch.object(cke, "get_json", return_value=None):  # MusicBrainz did not answer: not "unknown", not cached
        assert cke.mb_country("Throttled", cache) is None
    assert "Throttled" not in cache


def test_mb_find_id(tmp_path):
    ids = cke.Cache(tmp_path, "i")
    kr = {"artists": [{"id": "mb-uk", "name": "Twin", "country": "GB"}, {"id": "mb-kr", "name": "Twin", "country": "KR"}]}
    with mock.patch.object(cke, "get_json", return_value=kr):
        assert cke.mb_find_id("Twin", ids) == "mb-kr"  # the South Korean one of two namesakes
    with mock.patch.object(cke, "get_json", return_value={"artists": [{"id": "x", "name": "Other", "country": "KR"}]}):
        assert cke.mb_find_id("Twin2", ids) == "" and "Twin2" in ids  # no such Korean artist: remembered as ""
    with mock.patch.object(cke, "get_json", return_value=None):
        assert cke.mb_find_id("Down", ids) is None and "Down" not in ids  # no answer: not remembered


def test_mb_url_links_deezer_and_spotify(tmp_path):
    links = cke.Cache(tmp_path, "l")
    sp = "S" * 22
    rels = {"relations": [{"url": {"resource": "https://www.instagram.com/x"}}, {"url": {"resource": "https://www.deezer.com/artist/1234"}},
                          {"url": {"resource": f"https://open.spotify.com/artist/{sp}"}}]}
    with mock.patch.object(cke, "get_json", return_value=rels):
        assert cke.mb_url_links("m1", links) == {"deezer": 1234, "spotify": sp}
    with mock.patch.object(cke, "get_json", return_value={"relations": [{"url": {"resource": "https://www.deezer.com/en/artist/55"}},
                                                                    {"url": {"resource": f"https://open.spotify.com/intl-ko/artist/{sp}"}}]}):
        assert cke.mb_url_links("m2", links) == {"deezer": 55, "spotify": sp}  # language parts in the URLs
    with mock.patch.object(cke, "get_json", return_value={"relations": [{"url": {"resource": "https://open.spotify.com/track/abc"}}]}):
        assert cke.mb_url_links("m3", links) == {"deezer": 0, "spotify": ""} and "m3" in links  # nothing usable: remembered
    with mock.patch.object(cke, "get_json", return_value=None):
        assert cke.mb_url_links("m4", links) is None and "m4" not in links
    with mock.patch.object(cke, "get_json") as m:
        assert cke.mb_url_links("m1", links)["deezer"] == 1234 and not m.called


def test_spotify_artist_ids_from_reccobeats(tmp_path):
    cache = cke.Cache(tmp_path, "r")
    a1, a2 = "A" * 22, "B" * 22
    data = {"content": [{"isrc": "I1", "artists": [{"href": f"https://open.spotify.com/artist/{a1}"}]},
                        {"isrc": "I2", "artists": [{"href": f"https://open.spotify.com/artist/{a2}"}, {"href": "bad"}]}]}
    with mock.patch.object(cke, "get_json", return_value=data) as m:
        assert cke.spotify_artist_ids(["I1", "I2", "I3"], cache) == {a1, a2}  # I3 is unknown to ReccoBeats
    assert m.call_count == 1 and "ids=I1,I2,I3" in m.call_args.args[0]
    with mock.patch.object(cke, "get_json") as m:
        assert cke.spotify_artist_ids(["I1"], cache) == {a1} and not m.called  # cached
    with mock.patch.object(cke, "get_json", return_value={"content": []}):
        assert cke.spotify_artist_ids(["X1"], cache) is None  # nothing known: cannot verify
    with mock.patch.object(cke, "get_json") as m:
        cke.spotify_artist_ids([f"I{i}" for i in range(20)], cke.Cache(tmp_path, "r2"))
    assert m.call_args.args[0].count(",") == 3  # only a few songs are looked at


def test_check_identity_decisions(tmp_path):
    ids, links, recco = cke.Cache(tmp_path, "i"), cke.Cache(tmp_path, "l"), cke.Cache(tmp_path, "r")
    sp = lambda c: c * 22
    for mbid, v in {"mb-same": {"deezer": 11, "spotify": ""}, "mb-other": {"deezer": 99, "spotify": ""},
                    "mb-none": {"deezer": 0, "spotify": ""}, "mb-sp-ok": {"deezer": 0, "spotify": sp("A")},
                    "mb-sp-bad": {"deezer": 0, "spotify": sp("B")}}.items():
        links.put(mbid, v, save_every=1)
    ids.put("Found Namesake", "mb-same", save_every=1); ids.put("No Korean Artist", "", save_every=1)
    for isrc, artist in {"s-ok": sp("A"), "s-bad": sp("C")}.items(): recco.put(isrc, [artist], save_every=1)
    artists = {1: {"name": "Unique", "n_exact": 1},
               2: {"name": "한글이름", "n_exact": 3},
               3: {"name": "Latin Name", "n_exact": 2},                       # has a Hangul song title
               11: {"name": "Linked", "n_exact": 2, "mb_id": "mb-same"},        # MusicBrainz links Deezer 11
               12: {"name": "Switched", "n_exact": 2, "mb_id": "mb-other"},     # MusicBrainz links Deezer 99
               13: {"name": "No Link Ambiguous", "n_exact": 2, "mb_id": "mb-none"},
               14: {"name": "No Korean Artist", "n_exact": 2},
               15: {"name": "Found Namesake", "n_exact": 2},                    # MB id found by name; links to 11 (not 15)
               16: {"name": "Spotify Ok", "n_exact": 2, "mb_id": "mb-sp-ok"},   # Spotify artist matches the songs
               17: {"name": "Spotify Wrong", "n_exact": 1, "mb_id": "mb-sp-bad"},  # ...does not match: a unique name is not enough
               18: {"name": "No Link Unique", "n_exact": 1, "mb_id": "mb-none"},
               19: {"name": "No MB Unique", "n_exact": 1}}
    mb_ids = ids
    ids.put("No MB Unique", "", save_every=1)
    artists[20] = {"name": "Korean Label", "n_exact": 3, "mb_id": "mb-none"}  # ambiguous, no link, but KR ISRCs
    artists[21] = {"name": "Foreign Label", "n_exact": 3, "mb_id": "mb-none"}  # ambiguous, no link, foreign ISRCs
    artists[22] = {"name": "Unique Foreign", "n_exact": 1, "mb_id": "mb-none"}  # unique: kept even with foreign ISRCs
    tracks = {3: [{"title": "사랑", "isrc": "x"}], 16: [{"title": "A", "isrc": "s-ok"}], 17: [{"title": "B", "isrc": "s-bad"}],
              20: [{"title": "A", "isrc": "KRA1"}, {"title": "B", "isrc": "KRA2"}, {"title": "C", "isrc": "QZA3"}],
              21: [{"title": "A", "isrc": "USA1"}, {"title": "B", "isrc": "KRA2"}, {"title": "C", "isrc": "QZA3"}],
              22: [{"title": "A", "isrc": "DKA1"}]}
    verdicts = cke.check_identity(artists, tracks, mb_ids, links, recco)
    status = {aid: v[0] for aid, v in verdicts.items()}
    assert status[1].startswith("unique name on Deezer")  # no MusicBrainz id: nothing to check, the name is unique
    assert status[2] == "Hangul name or songs" and status[3] == "Hangul name or songs"
    assert status[11] == "MusicBrainz links this Deezer artist" and verdicts[11][1] is None
    assert status[12].startswith("MusicBrainz links another") and verdicts[12][1] == 99
    assert status[13].startswith("rejected") and "no usable link" in status[13]
    assert status[14].startswith("rejected") and "no MusicBrainz artist" in status[14]
    assert status[15].startswith("MusicBrainz links another") and verdicts[15][1] == 11
    assert status[16] == "MusicBrainz links this Spotify artist"
    assert status[17].startswith("rejected") and "Spotify artist is not the one" in status[17]  # even with a unique name
    assert status[18].startswith("unique name on Deezer") and not status[18].startswith("rejected")
    assert status[19].startswith("unique name on Deezer")
    assert status[20] == "ISRC country code KR on most songs"  # 2 of 3 ISRCs start with KR
    assert status[21].startswith("rejected") and "no usable link" in status[21]  # only 1 of 3
    assert status[22].startswith("unique name on Deezer") and "no links" not in status[22] and not status[22].startswith("rejected")
    assert status[13].startswith("rejected")  # no tracks at all: no ISRC evidence either


def test_playlist_artists_from_the_first_matching_playlists(tmp_path):
    def fake(url, limiter, **kw):
        if "search/playlist" in url:
            return {"data": [{"id": 1, "nb_tracks": 50}, {"id": 2, "nb_tracks": 5}, {"id": 3, "nb_tracks": 900}, {"id": 4, "nb_tracks": 20}]}
        pid = url.split("/playlist/")[1].split("/")[0]
        return {"data": [{"artist": {"id": 10 + int(pid), "name": f"Artist{pid}"}}, {"artist": {"id": 99, "name": "Everywhere"}}]}
    cache = cke.Cache(tmp_path, "p")
    with mock.patch.object(cke, "get_json", side_effect=fake):
        out = cke.playlist_artists(["k-indie", "korean rock"], cache)
    assert set(out) == {11, 14, 99}  # playlists with 15..400 tracks only (ids 1 and 4)
    assert out[99]["queries"] == ["k-indie", "korean rock"] and out[11]["queries"] == ["k-indie", "korean rock"]


def test_artist_tracks_only_the_artists_own_tracks_with_isrc(tmp_path):
    def fake(url, limiter, **kw):
        if "/albums" in url:
            return {"data": [{"id": 7, "title": "A", "record_type": "album", "fans": 1}, {"id": 8, "title": "B", "record_type": "single", "fans": 1}]}
        return {"data": [{"isrc": "I1", "title": "Own", "artist": {"id": 5, "name": "Me"}},
                         {"isrc": "I2", "title": "Someone else's", "artist": {"id": 6, "name": "Other"}},
                         {"title": "No isrc", "artist": {"id": 5, "name": "Me"}}]}
    albums, tracks = cke.Cache(tmp_path, "al"), cke.Cache(tmp_path, "tr")
    with mock.patch.object(cke, "get_json", side_effect=fake) as m:
        out = cke.artist_tracks(5, 1, albums, tracks)
    assert [t["isrc"] for t in out] == ["I1"] and m.call_count == 2  # 1 albums request + 1 album (max_albums=1)
    with mock.patch.object(cke, "get_json") as m:
        assert cke.artist_tracks(5, 1, albums, tracks) == out and not m.called


def test_fetch_features_batches_of_40_popularity_missing_and_cache(tmp_path):
    isrcs = [f"I{i:03d}" for i in range(95)]
    calls = []
    def fake(url, limiter, **kw):
        calls.append(url)
        ids = url.split("ids=")[1].split(",")
        assert len(ids) <= 40
        if "audio-features" in url:
            return {"content": [{"isrc": i, "href": f"https://open.spotify.com/track/{'S' * 21}{i[-1]}", **{f: 0.5 for f in cke.FEATURES}}
                                for i in ids if i != "I010"]}  # one ISRC is unknown to ReccoBeats
        return {"content": [{"isrc": i, "popularity": 42} for i in ids]}
    cache = cke.Cache(tmp_path, "f")
    with mock.patch.object(cke, "get_json", side_effect=fake):
        out = cke.fetch_features(isrcs, cache)
    assert len(out) == 94 and "I010" not in out and out["I000"]["popularity"] == 42 and out["I000"]["spotify_id"].startswith("SSS")
    assert len(calls) == 6  # 3 batches x (features + popularity)
    with mock.patch.object(cke, "get_json") as m:
        assert len(cke.fetch_features(isrcs, cache)) == 94 and not m.called  # everything, the unknown one too, is cached


# ------------------------------------------------------------------ building the files
def feat(spotify_id, popularity=50, **kw):
    return {"spotify_id": spotify_id, "popularity": popularity, **{f: 0.5 for f in cke.FEATURES}, "tempo": 120.123456} | kw


A = "A" * 22
def test_build_rows_skips_and_dedupes():
    artists = {1: {"name": "Band", "genres": ["indie", "rock"], "source": "musicbrainz:indie", "country": "KR"},
               2: {"name": "Rapper", "genres": [], "source": "playlist:korean hip hop", "country": "KR"}}
    tracks = {1: [{"isrc": "I1", "title": "Song", "artist": "Band"},
                  {"isrc": "I2", "title": "Song - Remastered 2020", "artist": "Band"},   # same song, less popular
                  {"isrc": "I3", "title": "Song (Inst.)", "artist": "Band"},             # instrumental
                  {"isrc": "I4", "title": "No Features", "artist": "Band"},
                  {"isrc": "I5", "title": "No Spotify Id", "artist": "Band"},
                  {"isrc": "I6", "title": "Known Id", "artist": "Band"},
                  {"isrc": "I7", "title": "Known Title", "artist": "Band"},
                  {"isrc": "I9", "title": "Failed Analysis", "artist": "Band"}],
              2: [{"isrc": "I8", "title": "Rap", "artist": "Rapper"}, {"isrc": "I1", "title": "Song", "artist": "Band"}]}
    features = {"I1": feat("B" * 22, 70), "I2": feat("C" * 22, 20), "I3": feat("D" * 22), "I5": feat(""), "I6": feat(A),
                "I7": feat("E" * 22), "I8": feat("F" * 22, 10), "I9": feat("G" * 22, tempo=0.0)}
    rows, skipped = cke.build_rows(artists, tracks, features, {A}, {(cke.title_key("Known Title"), "band")})
    assert [r["track_name"] for r in rows] == ["Song", "Rap"]  # the most popular version of "Song" wins
    assert dict(skipped) == {"duplicate": 2, "instrumental": 1, "no features": 1, "no Spotify id": 1, "already in the dataset": 2, "tempo 0": 1}
    song, rap = rows
    assert list(song) == cke.COLUMNS and song["track_id"] == "B" * 22 and song["isrc"] == "I1" and song["popularity"] == 70
    assert song["tempo"] == 120.123 and song["genres"] == "indie;rock" and song["source"] == "musicbrainz:indie"
    assert rap["genres"] == "k-pop" and rap["source"] == "playlist:korean hip hop"  # a song always has a genre


def test_artist_summary_counts_sorts_and_protects_cells():
    rows = [{"artists": "=LOVE", "genres": "indie;folk", "popularity": 5, "track_name": "=Title"},
            {"artists": "=LOVE", "genres": "indie", "popularity": 50, "track_name": "Best"},
            {"artists": "Peppertones", "genres": "rock", "popularity": 1, "track_name": "One"}]
    rows[0]["isrc"], rows[1]["isrc"], rows[2]["isrc"] = "KRA1", "USA2", "KRA3"
    out = cke.artist_summary(rows, {"love": {"country": "KR"}, "peppertones": {"country": "n/a (Hangul name)"}})
    assert [a["korean_isrc_share"] for a in out] == [0.5, 1.0]
    assert [(a["artist"], a["song_count"]) for a in out] == [("'=LOVE", 2), ("Peppertones", 1)]
    assert out[0]["genres"] == "indie;folk" and out[0]["example_title"] == "Best"
    assert out[0]["musicbrainz_country"] == "KR" and out[1]["musicbrainz_country"] == "n/a (Hangul name)"  # looked up by norm(name): case and punctuation do not matter
    assert cke.artist_summary(rows, {})[0]["musicbrainz_country"] == ""  # unknown artist: empty


# ------------------------------------------------------------------ the whole script, everything mocked
def router(calls, namesakes=False):
    def fake(url, limiter, **kw):
        calls.append(url)
        from urllib.parse import unquote
        if namesakes and "musicbrainz.org" in url and "inc=url-rels" in url:  # MusicBrainz knows the right Deezer / Spotify page
            if "/mb3?" in url: return {"relations": [{"url": {"resource": "https://www.deezer.com/artist/8"}}]}
            if "/mb5?" in url: return {"relations": [{"url": {"resource": "https://open.spotify.com/artist/" + "V" * 22}}]}
            if "/mb6?" in url: return {"relations": [{"url": {"resource": "https://open.spotify.com/artist/" + "I" * 22}}]}
            return {"relations": []}
        if namesakes and "musicbrainz.org" in url and "tag%3A" in url and unquote(url.split("tag%3A")[1].split("&")[0]).strip('"') == "folk":
            return {"count": 2, "artists": [{"id": "mb5", "name": "Verified", "country": "KR", "tags": []},
                                            {"id": "mb6", "name": "Impostor", "country": "KR", "tags": []}]}
        if namesakes and "search/artist" in url and unquote(url.split("&q=")[1]) in ("Verified", "Impostor"):
            n = unquote(url.split("&q=")[1])
            return {"data": [{"id": 20, "name": n, "nb_fan": 90}, {"id": 21, "name": n, "nb_fan": 1}]} if n == "Verified" else \
                   {"data": [{"id": 22, "name": n, "nb_fan": 90}, {"id": 23, "name": n, "nb_fan": 1}]}
        if namesakes and "musicbrainz.org" in url and "tag%3A" in url and unquote(url.split("tag%3A")[1].split("&")[0]).strip('"') == "rock":
            return {"count": 2, "artists": [{"id": "mb3", "name": "Twin", "country": "KR", "tags": []},
                                            {"id": "mb4", "name": "Lonely", "country": "KR", "tags": []}]}
        if namesakes and "search/artist" in url and unquote(url.split("&q=")[1]) in ("Twin", "Lonely"):
            n = unquote(url.split("&q=")[1])  # two Deezer artists with each name; the bigger one is the wrong one
            return {"data": [{"id": 7, "name": "Twin", "nb_fan": 1000}, {"id": 8, "name": "Twin", "nb_fan": 5}]} if n == "Twin" else \
                   {"data": [{"id": 9, "name": "Lonely", "nb_fan": 50}, {"id": 10, "name": "Lonely", "nb_fan": 40}]}
        if "musicbrainz.org" in url and "tag%3A" in url:
            tag = unquote(url.split("tag%3A")[1].split("&")[0]).strip('"')
            if tag == "indie":
                return {"count": 1, "artists": [{"id": "mb1", "name": "Mock Band", "country": "KR", "tags": [{"name": "indie rock"}, {"name": "korean"}]}]}
            if tag == "hip hop":
                return {"count": 1, "artists": [{"id": "mb2", "name": "Mock Rapper", "country": "KR", "tags": [{"name": "hip hop"}]}]}
            return {"count": 0, "artists": []}
        if "musicbrainz.org" in url:  # artist country lookups of the playlist artists
            q = json.loads(json.dumps(__import__("urllib.parse", fromlist=["x"]).unquote(url)))
            if "Playlist KR" in q: return {"artists": [{"id": "mb-pl-kr", "name": "Playlist KR", "country": "KR"}]}
            return {"artists": [{"id": "mb-pl-uk", "name": "Playlist UK", "country": "GB"}]}
        if "search/artist" in url:
            name = __import__("urllib.parse", fromlist=["x"]).unquote(url.split("&q=")[1])
            ids = {"Mock Band": 1, "Mock Rapper": 2, "Playlist KR": 3}
            return {"data": [{"id": ids[name], "name": name, "nb_fan": 5}]} if name in ids else {"data": []}
        if "search/playlist" in url:
            return {"data": [{"id": 50, "nb_tracks": 30}]} if unquote(url.split("&q=")[1]) == "k-indie" else {"data": []}
        if "/playlist/" in url:
            return {"data": [{"artist": {"id": 3, "name": "Playlist KR"}}, {"artist": {"id": 4, "name": "Playlist UK"}}, {"artist": {"id": 5, "name": "한글가수"}}]}
        if "/albums" in url:
            aid = url.split("/artist/")[1].split("/")[0]
            return {"data": [{"id": int(aid) * 10, "title": f"Album{aid}", "record_type": "album", "fans": 1}]}
        if "/album/" in url:
            aid = int(url.split("/album/")[1].split("/")[0]) // 10
            names = {1: "Mock Band", 2: "Mock Rapper", 3: "Playlist KR", 5: "한글가수", 7: "Twin", 8: "Twin", 9: "Lonely", 10: "Lonely", 20: "Verified", 21: "Verified", 22: "Impostor", 23: "Impostor"}
            return {"data": [{"isrc": f"ISRC{aid}A", "title": f"Song {aid}A", "artist": {"id": aid, "name": names[aid]}},
                             {"isrc": f"ISRC{aid}B", "title": f"Song {aid}B (Inst.)", "artist": {"id": aid, "name": names[aid]}}]}
        if "audio-features" in url:
            ids = url.split("ids=")[1].split(",")
            return {"content": [{"isrc": i, "href": "https://open.spotify.com/track/" + i.rjust(22, "X"), **{f: 0.4 for f in cke.FEATURES}} for i in ids]}
        if "reccobeats" in url:  # popularity, and the Spotify artist ReccoBeats reports for the song
            def spotify_artist(isrc):
                aid = int(isrc[4:-1])
                return {20: "V" * 22, 22: "X" * 22}.get(aid, "Z" * 22)  # Verified's songs say V (MusicBrainz: V); Impostor's say X (MusicBrainz: I)
            return {"content": [{"isrc": i, "popularity": 33, "artists": [{"href": "https://open.spotify.com/artist/" + spotify_artist(i)}]}
                                for i in url.split("ids=")[1].split(",")]}
        raise AssertionError("unexpected url " + url)
    return fake


def run_main(tmp_path, *extra_args, namesakes=False):
    calls = []
    out, review = tmp_path / "songs.csv", tmp_path / "review.csv"
    with mock.patch.object(cke, "get_json", side_effect=router(calls, namesakes)), mock.patch.object(cke, "dataset_keys", return_value=(set(), set())):
        assert cke.main(["--cache-dir", str(tmp_path / "cache"), "--out", str(out), "--review", str(review),
                         "--rejected", str(tmp_path / "rejected.csv"), *extra_args]) == 0
    return calls, pd.read_csv(out), pd.read_csv(review)


def test_main_end_to_end_without_playlists(tmp_path):
    calls, songs, review = run_main(tmp_path, "--no-playlists")
    assert list(songs.columns) == cke.COLUMNS and set(songs.artists) == {"Mock Band", "Mock Rapper"}
    assert songs.track_name.tolist() == ["Song 1A", "Song 2A"]  # the "(Inst.)" versions are gone
    band = songs[songs.artists == "Mock Band"].iloc[0]
    assert band.genres == "indie;rock"  # the style of the search first (indie), then the mapped tags (indie rock -> indie, rock)
    assert songs[songs.artists == "Mock Rapper"].iloc[0].genres == "hip-hop" and band.source.startswith("musicbrainz:")
    assert list(review.columns) == ["artist", "song_count", "genres", "musicbrainz_country", "example_title", "identity_check", "korean_isrc_share"]
    assert review.musicbrainz_country.tolist() == ["KR", "KR"] and review.song_count.tolist() == [1, 1]
    assert all(c.startswith("unique name on Deezer") for c in review.identity_check)
    assert not any("playlist" in c for c in calls)
    # a second run uses the cache only and gives the same files
    calls2, songs2, review2 = run_main(tmp_path, "--no-playlists")
    assert calls2 == [] and songs2.equals(songs) and review2.equals(review)


def test_main_keeps_playlist_artists_only_if_korea_is_confirmed_or_the_name_has_hangul(tmp_path):
    calls, songs, review = run_main(tmp_path)
    assert set(songs.artists) == {"Mock Band", "Mock Rapper", "Playlist KR", "한글가수"}  # not "Playlist UK" (MusicBrainz says GB)
    country = dict(zip(review.artist, review.musicbrainz_country))
    assert country["Playlist KR"] == "KR" and country["한글가수"] == "n/a (Hangul name)"
    kr = songs[songs.artists == "Playlist KR"].iloc[0]
    assert kr.source == "playlist:k-indie" and kr.genres == "indie"  # genre from the playlist query
    from urllib.parse import unquote
    asked = [unquote(c) for c in calls if "musicbrainz.org" in c and "artist%3A" in c]
    assert any("Playlist UK" in c for c in asked) and not any("한글가수" in c for c in asked)  # the Hangul name is never looked up


def test_main_limit_artists_option(tmp_path):
    _, songs, _ = run_main(tmp_path, "--no-playlists", "--limit-artists", "1")
    assert set(songs.artists) == {"Mock Band"}


def test_the_script_never_needs_a_key_and_is_in_the_repo_folder():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "api_key" not in text.lower() and "os.environ" not in text and "Authorization" not in text
    assert SCRIPT.parent.name == "scripts"
    gitignore = (SCRIPT.parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "scripts/.cache/" in gitignore  # the download cache is not committed


def test_features_with_nulls_are_unavailable_not_a_crash(tmp_path):
    good = {"isrc": "G1", "href": "https://open.spotify.com/track/" + "G" * 22, **{f: 0.3 for f in cke.FEATURES}}
    nulls = {"isrc": "N1", "href": "https://open.spotify.com/track/" + "N" * 22, **{f: None for f in cke.FEATURES}}
    def fake(url, limiter, **kw):
        return {"content": [good, nulls]} if "audio-features" in url else {"content": []}
    cache = cke.Cache(tmp_path, "f")
    with mock.patch.object(cke, "get_json", side_effect=fake):
        out = cke.fetch_features(["G1", "N1"], cache)
    assert set(out) == {"G1"} and cache.get("N1") is False
    # a cache written by an older version may still hold such an entry: build_rows skips it instead of crashing
    old = {"spotify_id": "H" * 22, "popularity": 3, **{f: None for f in cke.FEATURES}}
    rows, skipped = cke.build_rows({1: {"name": "A", "genres": ["indie"], "source": "musicbrainz:indie", "country": "KR"}},
                                   {1: [{"isrc": "O1", "title": "Old", "artist": "A"}]}, {"O1": old}, set(), set())
    assert rows == [] and skipped["no features"] == 1


def test_main_switches_namesakes_to_the_deezer_page_musicbrainz_links_and_leaves_out_unverifiable_ones(tmp_path):
    calls, songs, review = run_main(tmp_path, "--no-playlists", namesakes=True)
    assert set(songs.artists) == {"Mock Band", "Mock Rapper", "Twin", "Verified"}  # "Lonely" and "Impostor" are left out
    twin = songs[songs.artists == "Twin"]
    assert twin.track_name.tolist() == ["Song 8A"]  # the songs of Deezer artist 8 (MusicBrainz's), not of 7 (more fans)
    check = dict(zip(review.artist, review.identity_check))
    assert check["Twin"].startswith("MusicBrainz links another") and check["Mock Band"].startswith("unique name on Deezer")
    assert check["Verified"] == "MusicBrainz links this Spotify artist"
    rejected = pd.read_csv(tmp_path / "rejected.csv")
    assert list(rejected.columns) == ["artist", "deezer_id", "reason", "source", "songs_found"]
    assert sorted(rejected.artist) == ["Impostor", "Lonely"]
    reasons = dict(zip(rejected.artist, rejected.reason))
    assert "no usable link" in reasons["Lonely"] and "Spotify artist is not the one" in reasons["Impostor"]
    assert set(rejected.songs_found) == {2}
