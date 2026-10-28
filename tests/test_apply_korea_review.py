import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
spec = importlib.util.spec_from_file_location("apply_korea_review", SCRIPTS / "apply_korea_review.py")
akr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(akr)
cke = akr.cke


@pytest.fixture(autouse=True)
def no_waiting():
    zero = cke.Limiter(0)
    with mock.patch.object(cke, "MB_LIMIT", zero), mock.patch.object(cke, "DEEZER_LIMIT", zero), \
            mock.patch.object(cke, "RECCO_LIMIT", zero), mock.patch.object(cke.time, "sleep"):
        yield


# ------------------------------------------------------------------ the rule
def test_korean_song_signs():
    assert akr.korean_song("Song", "Band", "KRA123") and akr.korean_song("Song", "Band", "kr0001")  # KR ISRC
    assert akr.korean_song("사랑", "Band", "USX1") and akr.korean_song("Song", "한글밴드", "USX1")  # Hangul title / artist
    assert akr.korean_song("Song (Feat. 윤하)", "Band", "USX1")  # a featured artist with a Hangul name
    assert not akr.korean_song("Song (feat. Someone)", "Band", "USX1") and not akr.korean_song("Song", "Band", None)
    assert not akr.korean_song("Sureña", "Black String", "QZ1")


def test_korean_share():
    songs = [("a", "x", "KRA1"), ("b", "x", "USA2"), ("사랑", "x", "USA3"), ("d", "x", "DKA4")]
    assert akr.korean_share(songs) == 0.5 and akr.korean_share([]) == 0.0 and akr.korean_share(iter(songs[:1])) == 1.0


def test_load_decisions_strips_and_adds_a_key(tmp_path):
    f = tmp_path / "d.csv"
    f.write_text("artist,list,decision,reason\n JAMBINAI ,rejected, rescue ,why\n", encoding="utf-8")
    d = akr.load_decisions(f)
    assert d.artist.iloc[0] == "JAMBINAI" and d.decision.iloc[0] == "rescue" and d.key.iloc[0] == "jambinai"


def test_genres_from_source():
    assert akr.genres_from_source("musicbrainz:indie+rock") == ["indie", "rock"]
    assert akr.genres_from_source("playlist:korean r&b+한국 힙합") == ["r-n-b", "hip-hop"]
    assert akr.genres_from_source("") == [] and akr.genres_from_source("playlist:unknown query") == []


def test_find_pages_exact_names_not_the_old_page_most_fans_first(tmp_path):
    cache = cke.Cache(tmp_path, "d")
    answers = {"잠비나이": [{"id": 5, "name": "잠비나이", "fans": 10}],
               "Jambinai": [{"id": 9, "name": "Jambinai", "fans": 500}, {"id": 7, "name": "Jambinai", "fans": 50}, {"id": 5, "name": "잠비나이", "fans": 10}]}
    with mock.patch.object(cke, "deezer_exact_matches", side_effect=lambda n, a, c, k: answers[n]):
        pages = akr.find_pages(["잠비나이", "Jambinai"], exclude_id=9, deezer_cache=cache)
    assert [p["id"] for p in pages] == [7, 5]  # 9 is the rejected namesake; the rest by fans; 5 only once


def test_best_page_needs_a_song_and_enough_korean_evidence_and_describes_every_page():
    korean = [{"isrc": f"KRA{i}", "title": f"t{i}", "artist": "A"} for i in range(5)]
    foreign = [{"isrc": f"USA{i}", "title": f"t{i}", "artist": "A"} for i in range(5)]
    mixed = [{"isrc": "KRA1", "title": "a", "artist": "A"}, {"isrc": "USA2", "title": "b", "artist": "A"}, {"isrc": "USA3", "title": "c", "artist": "A"}]
    tiny = [{"isrc": "KRE1", "title": "한 곡", "artist": "A"}]  # a Korean-named page often has a single song
    tracks = {1: korean, 2: foreign, 3: [], 4: mixed, 5: tiny}
    pages = [{"id": i, "name": f"P{i}", "fans": 5} for i in tracks]
    caches = {"albums": None, "tracks": None}
    with mock.patch.object(cke, "artist_tracks", side_effect=lambda aid, n, a, t: tracks[aid]):
        (page, got, share), seen = akr.best_page(pages, 5, caches)
        assert page["id"] == 1 and share == 1.0 and len(got) == 5 and len(seen) == 5
        assert seen[0] == "'P1' id 1 (5 fans): 5 songs, 100% Korean" and seen[2] == "'P3' id 3 (5 fans): 0 songs, 0% Korean"
        found, seen = akr.best_page([pages[1], pages[2], pages[3]], 5, caches)
        assert found is None and len(seen) == 3  # foreign / no songs / only 33%
        found, _ = akr.best_page([pages[4]], 5, caches)
        assert found[0]["id"] == 5 and found[1] == tiny  # one Korean song is enough
        found, _ = akr.best_page([pages[0], pages[4]], 5, caches)
        assert found[0]["id"] == 1  # the page with more evidence/songs wins when both are fully Korean


def test_load_korean_names(tmp_path):
    f = tmp_path / "names.csv"
    f.write_text("artist,korean_name,note\nJAMBINAI,잠비나이,\nJAMBINAI, 잠비 나이 ,\nToy,토이,\nEmpty,,\n", encoding="utf-8")
    assert akr.load_korean_names(f) == {"jambinai": ["잠비나이", "잠비 나이"], "toy": ["토이"]}
    assert akr.load_korean_names(tmp_path / "missing.csv") == {}


# ------------------------------------------------------------------ the whole script (network mocked)
def feats(i):
    return {f: 0.4 for f in cke.FEATURES}


def router(calls):
    def fake(url, limiter, **kw):
        calls.append(url)
        if "musicbrainz.org" in url and "inc=aliases" in url:
            if "mb-Jambinai" in url: return {"name": "Jambinai", "aliases": [{"name": "잠비나이"}, {"name": "JAMBINAI"}]}
            return {"name": "Other", "aliases": []}
        if "musicbrainz.org" in url:  # search by name
            name = unquote(url.split("artist%3A")[1].split("&")[0]).strip('"') if "artist%3A" in url else ""
            return {"artists": [{"id": "mb-" + name, "name": name, "country": "KR"}]}
        if "search/artist" in url:
            name = unquote(url.split("&q=")[1])
            if name == "잠비나이": return {"data": [{"id": 50, "name": "잠비나이", "nb_fan": 20}]}
            if name == "Jambinai": return {"data": [{"id": 51, "name": "Jambinai", "nb_fan": 900}]}  # the foreign namesake (the old page)
            if name == "Generic": return {"data": [{"id": 60, "name": "Generic", "nb_fan": 9}]}
            if name == "한글러": return {"data": [{"id": 70, "name": "한글러", "nb_fan": 1}]}  # found only through the Korean names file
            if name == "Mixed": return {"data": [{"id": 80, "name": "Mixed", "nb_fan": 3}, {"id": 81, "name": "Mixed", "nb_fan": 2}]}
            return {"data": []}
        if "/albums" in url:
            aid = int(url.split("/artist/")[1].split("/")[0])
            return {"data": [{"id": aid * 10, "title": f"Album{aid}", "record_type": "album", "fans": 1}]}
        if "/album/" in url:
            aid = int(url.split("/album/")[1].split("/")[0]) // 10
            kr = aid in (50, 70)
            def prefix(n): return "KR" if kr or (aid == 80 and n < 2) else "DK"  # page 80 is half Korean, half foreign ISRCs
            names = {50: "잠비나이", 70: "한글러", 51: "Pagey", 80: "Mixed", 81: "Mixed"}
            return {"data": [{"isrc": f"{prefix(n)}A{aid}{n}", "title": f"{'노래' if kr else 'Song'} {aid}-{n}", "artist": {"id": aid, "name": names.get(aid, "Generic")}}
                             for n in range(4)] if aid != 81 else []}
        if "audio-features" in url:
            return {"content": [{"isrc": i, "href": "https://open.spotify.com/track/" + i.rjust(22, "Q"), **feats(i)} for i in url.split("ids=")[1].split(",")]}
        if "reccobeats" in url:
            return {"content": [{"isrc": i, "popularity": 20} for i in url.split("ids=")[1].split(",")]}
        raise AssertionError("unexpected url " + url)
    return fake


def song(track_id, title, artist, isrc, genres="indie"):
    return {"track_id": track_id, "isrc": isrc, "track_name": title, "artists": artist, "popularity": 10, **{f: 0.5 for f in cke.FEATURES},
            "genres": genres, "source": "musicbrainz:indie"}


def setup_files(tmp_path):
    rows = ([song(f"R{i:021d}", f"Foreign {i}", "Foreign Namesake", f"ESA{i}") for i in range(3)]                   # remove
            + [song(f"G{i:021d}", f"노래 {i}", "Good Check", f"USA{i}") for i in range(4)]                          # check, passes (Hangul titles)
            + [song(f"B{i:021d}", f"Foreign {i}", "Bad Check", f"USA9{i}") for i in range(4)]                       # check, fails
            + [song(f"K{i:021d}", f"Member {i}", "Group Member", f"USA8{i}") for i in range(2)]                     # keep
            + [song(f"N{i:021d}", f"Untouched {i}", "Nobody Mentioned", f"USA7{i}") for i in range(2)])             # not in the review file
    songs = tmp_path / "korea_extra.csv"
    pd.DataFrame(rows).to_csv(songs, index=False)
    pd.DataFrame([{"artist": "Jambinai", "deezer_id": 51, "reason": "rejected: ...", "source": "musicbrainz:rock", "songs_found": 30},
                  {"artist": "Hanguler", "deezer_id": 72, "reason": "rejected: ...", "source": "playlist:korean indie", "songs_found": 8},
                  {"artist": "Generic", "deezer_id": 61, "reason": "rejected: ...", "source": "playlist:korean indie", "songs_found": 20},
                  {"artist": "KISS", "deezer_id": 62, "reason": "rejected: ...", "source": "musicbrainz:rock", "songs_found": 90}]
                 ).to_csv(tmp_path / "rejected.csv", index=False)
    pd.DataFrame([{"artist": a, "song_count": 1, "genres": "indie", "musicbrainz_country": "KR", "example_title": "x", "identity_check": "old evidence", "korean_isrc_share": 0.0}
                  for a in ("Foreign Namesake", "Good Check", "Bad Check", "Group Member", "Nobody Mentioned")]).to_csv(tmp_path / "artists.csv", index=False)
    decisions = [("Foreign Namesake", "kept", "remove"), ("Good Check", "kept", "check"), ("Bad Check", "kept", "check"), ("Group Member", "kept", "keep"),
                 ("Jambinai", "rejected", "rescue"), ("Hanguler", "rejected", "rescue"), ("Generic", "rejected", "check"), ("KISS", "rejected", "keep_out"), ("Gone", "kept", "remove")]
    pd.DataFrame([{"artist": a, "list": l, "decision": d, "reason": "r"} for a, l, d in decisions]).to_csv(tmp_path / "review.csv", index=False)
    (tmp_path / "names.csv").write_text("artist,korean_name,note\nHanguler,한글러,\n", encoding="utf-8")
    return songs


def run(tmp_path):
    songs = setup_files(tmp_path)
    calls = []
    with mock.patch.object(cke, "get_json", side_effect=router(calls)), mock.patch.object(cke, "dataset_keys", return_value=(set(), set())):
        report = akr.main(["--review", str(tmp_path / "review.csv"), "--songs", str(songs), "--artists-file", str(tmp_path / "artists.csv"),
                           "--rejected-file", str(tmp_path / "rejected.csv"), "--cache-dir", str(tmp_path / "cache"),
                           "--korean-names", str(tmp_path / "names.csv"), "--overrides", str(tmp_path / "overrides.csv")])
    return report, calls


def test_main_applies_every_decision(tmp_path):
    report, calls = run(tmp_path)
    out = pd.read_csv(tmp_path / "korea_extra.csv")
    artists = set(out.artists)
    assert "Foreign Namesake" not in artists  # remove
    assert "Good Check" in artists and "Bad Check" not in artists  # check: Hangul titles pass, foreign titles fail
    assert {"Group Member", "Nobody Mentioned"} <= artists  # keep / not mentioned: untouched
    assert "잠비나이" in artists and out[out.artists == "잠비나이"].shape[0] == 4  # rescued through the Hangul alias
    assert "한글러" in artists and out[out.artists == "한글러"].shape[0] == 4  # rescued through the Korean names file
    assert "Generic" not in artists  # its only page has foreign ISRCs and titles: not verified
    assert list(out.columns) == cke.COLUMNS and out.track_id.is_unique
    rescued = out[out.artists == "잠비나이"]
    assert set(rescued.genres) == {"rock"} and rescued.source.str.startswith("review-rescue:musicbrainz:rock").all()  # genres from the old source
    assert rescued.isrc.str.startswith("KR").all() and rescued.track_id.str.len().eq(22).all()

    groups = {}
    for group, artist, n, note in report: groups.setdefault(group, []).append((artist, n))
    assert groups["removed"] == [("Foreign Namesake", 3)] or ("Foreign Namesake", 3) in groups["removed"]
    assert ("Gone", 0) in groups["removed"]  # a decision for an artist that is not in the file: nothing to remove
    assert groups["dropped after check"] == [("Bad Check", 4)] and groups["kept after check"] == [("Good Check", 4)]
    assert groups["rescued"] == [("Jambinai", 4), ("Hanguler", 4)] and groups["still unverified"] == [("Generic", 20)]
    note = next(r[3] for r in report if r[1] == "Generic")
    assert "searched Generic" in note and "'Generic' id 60 (9 fans): 4 songs, 0% Korean" in note  # says why it failed
    assert not any("KISS" in r for r in report)  # keep_out: nothing

    # the artist file follows the data; the rejected file loses the rescued artist
    summary = pd.read_csv(tmp_path / "artists.csv")
    assert set(summary.artist) == artists and summary[summary.artist == "잠비나이"].song_count.iloc[0] == 4
    assert summary[summary.artist == "Good Check"].identity_check.iloc[0] == "old evidence"  # kept rows keep their evidence
    assert "found by review" in summary[summary.artist == "잠비나이"].identity_check.iloc[0]
    rejected = pd.read_csv(tmp_path / "rejected.csv")
    assert sorted(rejected.artist) == ["Generic", "KISS"]  # both rescued artists are gone from the rejected list
    # the Hangul alias and the name were both searched on Deezer, and the old namesake page (51) was not used
    searched = [unquote(c.split("&q=")[1]) for c in calls if "search/artist" in c]
    assert "잠비나이" in searched and "Jambinai" in searched and not any("/artist/51/" in c for c in calls)


def test_the_rule_also_applies_to_the_songs_that_are_actually_added(tmp_path):
    # the page passes (4 of 5 songs Korean) but only the foreign song has audio features, so nothing is added
    songs = setup_files(tmp_path)
    page_tracks = [{"isrc": f"KRA{i}", "title": f"t{i}", "artist": "Jambinai", "artist_id": 50} for i in range(4)] + [{"isrc": "DKA9", "title": "x", "artist": "Jambinai", "artist_id": 50}]
    base = router([])

    def fake(url, limiter, **kw):
        if "audio-features" in url:  # only the foreign song has features
            return {"content": [{"isrc": "DKA9", "href": "https://open.spotify.com/track/" + "Q" * 22, **feats("DKA9")}]}
        return base(url, limiter, **kw)
    with mock.patch.object(cke, "get_json", side_effect=fake), mock.patch.object(cke, "dataset_keys", return_value=(set(), set())), \
            mock.patch.object(cke, "artist_tracks", side_effect=lambda aid, n, a, t: page_tracks if aid == 50 else []):
        report = akr.main(["--review", str(tmp_path / "review.csv"), "--songs", str(songs), "--artists-file", str(tmp_path / "artists.csv"),
                           "--rejected-file", str(tmp_path / "rejected.csv"), "--cache-dir", str(tmp_path / "cache"), "--korean-names", str(tmp_path / "names.csv"), "--overrides", str(tmp_path / "overrides.csv")])
    note = next(r[3] for r in report if r[1] == "Jambinai")
    assert next(r[0] for r in report if r[1] == "Jambinai") == "still unverified" and "passed (80%) but only 0% of its 1 songs" in note
    assert "잠비나이" not in set(pd.read_csv(songs).artists)


def test_main_twice_gives_the_same_result(tmp_path):
    run(tmp_path)
    first = pd.read_csv(tmp_path / "korea_extra.csv")
    seen = []
    with mock.patch.object(cke, "get_json", side_effect=lambda url, *a, **k: seen.append(url)), mock.patch.object(cke, "dataset_keys", return_value=(set(), set())):
        report2 = akr.main(["--review", str(tmp_path / "review.csv"), "--songs", str(tmp_path / "korea_extra.csv"), "--artists-file", str(tmp_path / "artists.csv"),
                            "--rejected-file", str(tmp_path / "rejected.csv"), "--cache-dir", str(tmp_path / "cache"),
                            "--korean-names", str(tmp_path / "names.csv"), "--overrides", str(tmp_path / "overrides.csv")])
    assert pd.read_csv(tmp_path / "korea_extra.csv").equals(first)  # already applied: nothing changes...
    assert seen == []  # ...and the network is not asked at all (not even for the foreign namesake page)
    assert ("already rescued", "Jambinai", 4, "songs are already in the file") in report2
    assert ("already rescued", "Hanguler", 4, "songs are already in the file") in report2


def test_explicit_overrides_page_and_kr_isrc_modes(tmp_path):
    songs = setup_files(tmp_path)
    pd.DataFrame([{"artist": "Pagey", "list": "rejected", "decision": "rescue", "reason": "r"},
                  {"artist": "Mixed", "list": "rejected", "decision": "rescue", "reason": "r"}]).to_csv(tmp_path / "extra_decisions.csv", index=False)
    d = pd.concat([pd.read_csv(tmp_path / "review.csv"), pd.read_csv(tmp_path / "extra_decisions.csv")])
    d.to_csv(tmp_path / "review.csv", index=False)
    rej = pd.read_csv(tmp_path / "rejected.csv")
    pd.concat([rej, pd.DataFrame([{"artist": "Pagey", "deezer_id": 51, "reason": "x", "source": "musicbrainz:rock", "songs_found": 4},
                                   {"artist": "Mixed", "deezer_id": 80, "reason": "x", "source": "playlist:korean indie", "songs_found": 4}])]).to_csv(tmp_path / "rejected.csv", index=False)
    pd.DataFrame([{"artist": "Pagey", "mode": "page", "pages": "51", "note": "the real page; foreign-looking ISRCs are expected"},
                  {"artist": "Mixed", "mode": "kr_isrc", "pages": "", "note": "only KR ISRC songs"},
                  {"artist": "Generic", "mode": "kr_isrc", "pages": "", "note": "has none"}]).to_csv(tmp_path / "overrides.csv", index=False)
    calls = []
    with mock.patch.object(cke, "get_json", side_effect=router(calls)), mock.patch.object(cke, "dataset_keys", return_value=(set(), set())):
        report = akr.main(["--review", str(tmp_path / "review.csv"), "--songs", str(songs), "--artists-file", str(tmp_path / "artists.csv"),
                           "--rejected-file", str(tmp_path / "rejected.csv"), "--cache-dir", str(tmp_path / "cache"),
                           "--korean-names", str(tmp_path / "names.csv"), "--overrides", str(tmp_path / "overrides.csv")])
    out = pd.read_csv(songs)
    pagey = out[out.artists == "Pagey"]
    assert len(pagey) == 4 and pagey.isrc.str.startswith("DK").all()  # mode page: all songs, whatever their ISRCs
    assert set(pagey.genres) == {"rock"} and pagey.source.eq("review-override:page").all()  # genres from the rejected file's source
    mixed = out[out.artists == "Mixed"]
    assert len(mixed) == 2 and mixed.isrc.str.startswith("KR").all() and mixed.source.eq("review-override:kr_isrc").all()  # only KR ISRCs
    assert set(mixed.genres) == {"indie"}
    assert "Generic" not in set(out.artists)  # nothing to add

    groups = {}
    for group, artist, n, note in report: groups.setdefault(group, []).append((artist, n))
    assert groups["override added"] == [("Pagey", 4), ("Mixed", 2)] and groups["override: nothing to add"] == [("Generic", 0)]
    assert not any(r[1] in ("Pagey", "Mixed", "Generic") and r[0] in ("rescued", "still unverified") for r in report)  # the rule is not applied to them
    summary = pd.read_csv(tmp_path / "artists.csv")
    assert "explicit override" in summary[summary.artist == "Pagey"].identity_check.iloc[0]
    assert "Pagey" not in set(pd.read_csv(tmp_path / "rejected.csv").artist)  # no longer left out
    searched = [unquote(c.split("&q=")[1]) for c in calls if "search/artist" in c]
    assert "Pagey" not in searched  # mode page does not search by name

    # a second run recognizes what it did and asks for nothing
    seen = []
    with mock.patch.object(cke, "get_json", side_effect=lambda url, *a, **k: seen.append(url)), mock.patch.object(cke, "dataset_keys", return_value=(set(), set())):
        report2 = akr.main(["--review", str(tmp_path / "review.csv"), "--songs", str(songs), "--artists-file", str(tmp_path / "artists.csv"),
                            "--rejected-file", str(tmp_path / "rejected.csv"), "--cache-dir", str(tmp_path / "cache"),
                            "--korean-names", str(tmp_path / "names.csv"), "--overrides", str(tmp_path / "overrides.csv")])
    assert pd.read_csv(songs).equals(out)
    assert ("already added (override)", "Pagey", 4, "songs are already in the file") in report2 and ("already added (override)", "Mixed", 2, "songs are already in the file") in report2


def test_load_overrides_validates(tmp_path):
    f = tmp_path / "o.csv"
    f.write_text('artist,mode,pages,note\nJAMBINAI,page,3720001 5,why\nToy,kr_isrc,,why\n', encoding="utf-8")
    o = akr.load_overrides(f)
    assert o[0] == {"artist": "JAMBINAI", "key": "jambinai", "mode": "page", "pages": [3720001, 5], "note": "why"} and o[1]["pages"] == []
    assert akr.load_overrides(tmp_path / "missing.csv") == []
    f.write_text("artist,mode,pages,note\nX,everything,,n\n", encoding="utf-8")
    with pytest.raises(ValueError): akr.load_overrides(f)
    f.write_text("artist,mode,pages,note\nX,page,,n\n", encoding="utf-8")
    with pytest.raises(ValueError): akr.load_overrides(f)


def test_the_repos_override_file_is_what_the_user_asked_for():
    o = {x["artist"]: x for x in akr.load_overrides(akr.OVERRIDES)}
    assert o["JAMBINAI"]["mode"] == "page" and o["JAMBINAI"]["pages"] == [3720001]  # the real band page, UK ISRCs expected
    assert o["Exhibition"]["mode"] == "kr_isrc" and o["Toy"]["mode"] == "kr_isrc"  # English-named pages: only KR ISRC songs
