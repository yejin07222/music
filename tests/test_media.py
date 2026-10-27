import io
import json
from unittest import mock

import media

ID = "3bNv3VuUOKgrf5hu3YcuRo"
PREVIEW = "https://cdnt-preview.dzcdn.net/api/1/1/3/4/6/0/abc.mp3?hdnea=exp=1~acl=/x*~hmac=y"
COVER = "https://cdn-images.dzcdn.net/images/cover/478a/250x250-000000-80-0-0.jpg"


def test_spotify_embed_only_for_valid_ids():
    assert media.spotify_embed_url(ID) == f"https://open.spotify.com/embed/track/{ID}"
    for bad in ["", None, "short", ID + "x", 'abc"><script>alert(1)</script>', "a/b" + ID[3:]]:
        assert media.spotify_embed_url(bad) is None


def test_deezer_player_escapes_and_hides_on_error():
    html = media.deezer_player_html(PREVIEW, COVER)
    assert html.count("<audio") == 1 and html.count("<img") == 1
    assert html.count("onerror=\"this.style.display='none'\"") == 2  # both hide themselves
    assert "&amp;" not in PREVIEW or "&amp;" in html
    # only one of them is fine; nothing valid means no player
    assert "<audio" not in media.deezer_player_html(None, COVER) and "<img" not in media.deezer_player_html(PREVIEW, None)
    assert media.deezer_player_html(None, None) is None


def test_deezer_player_rejects_foreign_or_unsafe_urls():
    for bad in [
        "http://cdnt-preview.dzcdn.net/a.mp3",             # not https
        "https://evil.example.com/a.mp3",                    # other host
        "https://dzcdn.net.evil.com/a.mp3",                  # look-alike host
        "javascript:alert(1)",
        'https://cdn-images.dzcdn.net/a.jpg" onerror="alert(1)',  # quote injection
    ]:
        out = media.deezer_player_html(bad, bad)
        assert out is None or 'onerror="alert' not in out and "evil" not in out and "javascript" not in out
    out = media.deezer_player_html(PREVIEW, 'https://cdn-images.dzcdn.net/a.jpg"><script>x</script>')
    assert out is None or "<script>" not in out


def _oembed(thumb):
    resp = mock.MagicMock()
    resp.__enter__.return_value = io.BytesIO(json.dumps({"thumbnail_url": thumb}).encode())
    return resp


def test_fetch_cover():
    good = "https://image-cdn-ak.spotifycdn.com/image/ab67616d00001e02abc"
    with mock.patch("urllib.request.urlopen", return_value=_oembed(good)) as m:
        assert media.fetch_cover(ID) == good
    assert m.call_args.kwargs["timeout"] == media.COVER_TIMEOUT_SECONDS
    assert m.call_args.args[0].get_header("User-agent") == media.USER_AGENT
    with mock.patch("urllib.request.urlopen", return_value=_oembed("https://evil.example.com/x.jpg")):
        assert media.fetch_cover(ID) is None
    for exc in [TimeoutError(), OSError("down"), ValueError("bad")]:
        with mock.patch("urllib.request.urlopen", side_effect=exc):
            assert media.fetch_cover(ID) is None
    with mock.patch("urllib.request.urlopen") as m:
        assert media.fetch_cover("not an id") is None and not m.called


def test_covers_are_parallel_cached_and_failures_do_not_raise():
    media._cover_cache.clear()
    ids = [("%022d" % i) for i in range(5)]
    with mock.patch.object(media, "fetch_cover", side_effect=lambda i: None if i.endswith("3") else f"https://i.scdn.co/{i}") as m:
        out = media.covers(ids + ids[:2])
        assert out[ids[0]] == f"https://i.scdn.co/{ids[0]}" and out[ids[3]] is None and len(out) == 5
        assert m.call_count == 5
        media.covers(ids)
        assert m.call_count == 5  # everything, even the failure, came from the cache
    media._cover_cache.clear()


def test_listen_links_for_a_dataset_song():
    links = dict(media.listen_links("Adele;Someone Else", "Someone Like You (Live)", track_id=ID))
    assert links["Spotify"] == f"https://open.spotify.com/track/{ID}"
    assert links["YouTube"] == "https://www.youtube.com/results?search_query=Adele+Someone+Else+Someone+Like+You+%28Live%29"
    assert "YouTube Music" not in links and "Deezer" not in links


def test_listen_links_for_a_deezer_song_use_deezer_not_spotify():
    links = dict(media.listen_links("The Weeknd", "Is There Someone Else?", deezer_link="https://www.deezer.com/track/1614228242"))
    assert links["Deezer"] == "https://www.deezer.com/track/1614228242" and "Spotify" not in links
    assert "Is+There+Someone+Else%3F" in links["YouTube"]
    # an unusable Deezer link is dropped; the YouTube searches stay
    assert [l for l, _ in media.listen_links("A", "B", deezer_link="https://evil.example.com/x")] == ["YouTube"]


def test_listen_links_encode_special_characters_and_survive_odd_input():
    q = dict(media.listen_links("AC/DC", 'Rock & "Roll" #1 / 한글', track_id=ID))["YouTube"]
    assert "&" not in q.split("search_query=")[1] and '"' not in q and "#" not in q and " " not in q
    assert "%ED%95%9C%EA%B8%80" in q  # Hangul is percent-encoded UTF-8
    assert media.listen_links("", "", track_id="bad id") == []


def _deezer(items):
    resp = mock.MagicMock()
    resp.__enter__.return_value = io.BytesIO(json.dumps({"data": items}).encode())
    return resp


def _item(title, artist, cover="https://cdn-images.dzcdn.net/images/cover/abc/250x250.jpg"):
    return {"title": title, "artist": {"name": artist}, "album": {"cover_medium": cover}}


def test_deezer_cover_fallback_needs_artist_and_title_to_match():
    ok = _deezer([_item("Solo (Reprise)", "Frank Ocean", "https://cdn-images.dzcdn.net/other.jpg"),
                  _item("Solo", "Frank Ocean"), _item("Solo", "Someone Else", "https://cdn-images.dzcdn.net/wrong.jpg")])
    with mock.patch("urllib.request.urlopen", return_value=ok) as m:
        assert media.fetch_cover_from_deezer("Frank Ocean;Someone", "Solo") == "https://cdn-images.dzcdn.net/other.jpg"
    assert m.call_args.args[0].get_header("User-agent") == media.USER_AGENT and m.call_args.kwargs["timeout"] == media.COVER_TIMEOUT_SECONDS
    for items in ([_item("Solo", "Someone Else")], [_item("Another Song", "Frank Ocean")], [], [_item("Solo", "Frank Ocean", "https://evil.example.com/x.jpg")]):
        with mock.patch("urllib.request.urlopen", return_value=_deezer(items)):
            assert media.fetch_cover_from_deezer("Frank Ocean", "Solo") is None
    for exc in (TimeoutError(), OSError("down"), ValueError("bad")):
        with mock.patch("urllib.request.urlopen", side_effect=exc):
            assert media.fetch_cover_from_deezer("Frank Ocean", "Solo") is None
    assert media.fetch_cover_from_deezer("", "Solo") is None and media.fetch_cover_from_deezer("A", "") is None


def test_covers_fall_back_to_deezer_only_when_info_is_given():
    media._cover_cache.clear()
    with mock.patch.object(media, "fetch_cover", return_value=None), \
            mock.patch.object(media, "fetch_cover_from_deezer", return_value="https://cdn-images.dzcdn.net/x.jpg") as dz:
        assert media.covers(["a" * 22])["a" * 22] is None and not dz.called  # no info: no fallback
        media._cover_cache.clear()
        assert media.covers(["b" * 22], info={"b" * 22: ("Frank Ocean", "Solo")}) == {"b" * 22: "https://cdn-images.dzcdn.net/x.jpg"}
        dz.assert_called_once_with("Frank Ocean", "Solo")
    media._cover_cache.clear()


def test_failed_cover_lookups_are_retried_later_but_found_ones_are_kept():
    media._cover_cache.clear()
    clock = [1000.0]
    now = lambda: clock[0]
    answers = {"f" * 22: None, "g" * 22: "https://i.scdn.co/g"}
    with mock.patch.object(media, "fetch_cover", side_effect=lambda i: answers[i]) as m:
        media.covers(list(answers), now=now)
        assert m.call_count == 2
        media.covers(list(answers), now=now)
        assert m.call_count == 2  # both remembered
        clock[0] += media.COVER_RETRY_SECONDS + 1
        answers["f" * 22] = "https://i.scdn.co/f"  # the service works again
        out = media.covers(list(answers), now=now)
        assert m.call_count == 3 and out["f" * 22] == "https://i.scdn.co/f" and out["g" * 22] == "https://i.scdn.co/g"
    media._cover_cache.clear()


def test_links_markdown():
    out = media.links_markdown([("Spotify", "https://open.spotify.com/track/" + ID), ("YouTube", "https://a.com/x(1) y")])
    assert out == f"듣기: [Spotify](https://open.spotify.com/track/{ID}) · [YouTube](https://a.com/x%281%29%20y)"
    assert media.links_markdown([]) is None
