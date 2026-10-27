from pathlib import Path

from streamlit.testing.v1 import AppTest

from countries import COUNTRY_GENRES

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_country_dropdown_order():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    box = at.selectbox[0]
    assert box.label == "나라 선택"
    assert box.options[:4] == ["한국", "일본", "영어권", "중국"]
    assert box.options[4:] == ["홍콩", "인도", "이란", "튀르키예", "말레이시아", "브라질", "프랑스어", "독일", "스웨덴", "스페인어"]
    assert len(box.options) == len(COUNTRY_GENRES) + 1  # every country, English-language included
    assert box.value == "South Korea"  # the key stays unchanged; only the label is Korean
    # the keys behind the labels still work: pick 영어권 and search a song
    at.text_input[0].set_value("Someone Like You").run()
    at.selectbox[0].set_value("English-language").run()
    assert not at.exception and _table_html(at).count('class="row"') == 10


def _search(q, *patches):
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        at = AppTest.from_file(APP, default_timeout=120).run()
        at.text_input[0].set_value(q).run()
    return at


def _table_html(at):
    """The results table (the iframe that has HTML instead of a URL)."""
    pages = [e.proto.srcdoc for e in at.get("iframe") if getattr(e.proto, "srcdoc", "")]
    return next((p for p in pages if "<table" in p), None)


def _headers(html):
    import re

    return re.findall(r"<th[^>]*>([^<]*)</th>", html)


def test_players_covers_and_listen_links_for_a_dataset_song():
    from unittest import mock

    import media

    covers = lambda ids: {i: "https://image-cdn-ak.spotifycdn.com/image/x" for i in ids}
    at = _search("Someone Like You", mock.patch.object(media, "covers", side_effect=covers))
    assert not at.exception
    assert len(at.get("iframe")) == 3  # my song's player, the table, and the picked result's player
    html = _table_html(at)
    assert _headers(html) == ["순위", "앨범", "제목", "가수", ""]  # covers shown, link header empty
    assert html.count('class="row"') == 10 and html.count('class="play"') == 10 and html.count('class="yt"') == 10
    assert html.count('href="https://open.spotify.com/track/') == 10
    assert html.count('href="https://www.youtube.com/results?search_query=') == 10
    assert "music.youtube.com" not in html and html.count('target="_blank"') == 20
    text = " ".join(m.value for m in at.markdown)
    assert "https://open.spotify.com/track/3bNv3VuUOKgrf5hu3YcuRo" in text  # Adele's own links


def test_covers_or_players_failing_do_not_break_the_app():
    from unittest import mock

    import media
    import streamlit as st

    at = _search("Someone Like You", mock.patch.object(media, "covers", side_effect=RuntimeError("down")),
                 mock.patch.object(st, "iframe", side_effect=RuntimeError("blocked")))
    assert not at.exception
    table = at.dataframe[0].value  # the table falls back to a plain one without icons
    assert table.columns.tolist() == ["제목", "가수"] and len(table) == 10 and len(at.get("iframe")) == 0
    assert len(at.get("vega_lite_chart")) == 1  # the chart is still there

    at = _search("Someone Like You", mock.patch.object(media, "covers", side_effect=RuntimeError("down")))
    html = _table_html(at)
    assert not at.exception and _headers(html) == ["순위", "제목", "가수", ""]  # no covers: that column is left out
