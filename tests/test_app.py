from pathlib import Path

from streamlit.testing.v1 import AppTest

from countries import COUNTRY_GENRES

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_country_dropdown_order():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    box = at.selectbox[0]
    assert box.label == "나라 선택"
    assert box.options[:5] == ["전체", "한국", "일본", "영어권", "중국"]
    assert box.options[5:] == ["홍콩", "인도", "이란", "튀르키예", "말레이시아", "브라질", "프랑스어", "독일", "스웨덴", "스페인어"]
    assert len(box.options) == len(COUNTRY_GENRES) + 2  # every country, English-language and 전체 included
    assert box.value == "All"  # the key stays unchanged; only the label is Korean
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
    """The results list (the iframe whose HTML has result rows)."""
    pages = [e.proto.srcdoc for e in at.get("iframe") if getattr(e.proto, "srcdoc", "")]
    return next((p for p in pages if 'class="row"' in p), None)


def _card_html(at):
    pages = [e.proto.srcdoc for e in at.get("iframe") if getattr(e.proto, "srcdoc", "")]
    return next((p for p in pages if 'class="song"' in p), None)


def test_players_covers_and_listen_links_for_a_dataset_song():
    from unittest import mock

    import media

    covers = lambda ids, **kwargs: {i: "https://image-cdn-ak.spotifycdn.com/image/x" for i in ids}
    at = _search("Someone Like You", mock.patch.object(media, "covers", side_effect=covers))
    assert not at.exception
    assert len(at.get("iframe")) == 3  # my song's card, the list, the picked result's player (none under the card)
    html = _table_html(at)
    assert html.count("<img") == 10 and "<th" not in html  # covers shown, no header row
    assert html.count('class="row"') == 10 and html.count('class="play"') == 10 and html.count('class="yt"') == 10
    card = _card_html(at)
    assert "내가 고른 곡" in card and "Someone Like You" in card and "Adele" in card and 'class="play"' in card
    assert "https://open.spotify.com/track/3bNv3VuUOKgrf5hu3YcuRo" in card
    assert html.count('href="https://open.spotify.com/track/') == 10
    assert html.count('href="https://www.youtube.com/results?search_query=') == 10
    assert "music.youtube.com" not in html and html.count('target="_blank"') == 20
    assert "듣기:" not in " ".join(m.value for m in at.markdown)  # no text links any more


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
    assert not at.exception and html.count('class="row"') == 10 and "<img" not in html  # no covers: left out


def test_all_countries_is_the_default_and_has_no_country_column():
    from unittest import mock

    import media

    no_covers = mock.patch.object(media, "covers", return_value={})
    at = _search("Someone Like You", no_covers)  # the default selection is 전체
    assert not at.exception and at.selectbox[0].value == "All"
    html = _table_html(at)
    assert html.count('class="row"') == 10 and "나라" not in html
    assert any("전체 음악 중 분위기가 비슷한 곡" in m.value and "sec-title" in m.value for m in at.markdown)

    with no_covers:
        at.selectbox[0].set_value("South Korea").run()
    assert not at.exception and _table_html(at).count('class="row"') == 10


def test_nothing_but_the_search_box_before_typing():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception and not at.info  # no blue info box
    assert [t.label for t in at.text_input] == ["노래 제목이나 가수 이름"] and len(at.selectbox) == 1
    assert not at.subheader and not at.get("iframe") and not at.dataframe and not at.slider
    assert at.title == [] and any('Find <span class="accent"' in m.value and "Similar</span> Songs" in m.value for m in at.markdown)


def test_new_look_pieces():
    import re
    import json
    from unittest import mock

    import media
    import results_table as rt

    at = _search("Someone Like You", mock.patch.object(media, "covers", return_value={}))
    text = " ".join(m.value for m in at.markdown)
    assert "Pretendard" in text and "Noto+Sans+KR" in text  # fonts: Pretendard for the title only, Noto Sans KR otherwise
    rules = re.findall(r"([^{}]+)\{[^{}]*Pretendard[^{}]*\}", text)
    assert [r.strip() for r in rules] == ["h1.app-title"]  # the only rule that uses Pretendard is the title's

    # "분위기 비교": its own heading, and in the box the subtitle on one line with the legend on its own line below
    assert any(m.value == '<div class="sec-title">분위기 비교</div>' for m in at.markdown)
    block = next(m.value for m in at.markdown if 'class="sec-sub"' in m.value)
    assert block.index('class="sec-sub"') < block.index('class="legend"')
    sub = re.search(r'<div class="sec-sub">(.*?)</div>', block).group(1)
    assert sub.startswith("Someone Like You vs 1위 ") and "dot" not in sub  # no dots in the subtitle
    legend = re.search(r'<div class="legend">(.*)</div>', block).group(1)
    assert legend.count('class="dot"') == 2 and "#A9B8F0" in legend and "#2F49C8" in legend
    assert "내가 고른 곡" in legend and "1위 추천 곡" in legend

    # the section is one box styled like the results list box
    compare = re.search(r"\.st-key-compare \{([^}]*)\}", text).group(1)
    list_css = rt.results_list([]).split("<style>")[1].split("</style>")[0]
    list_box = re.search(r"\.list \{([^}]*)\}", list_css).group(1)
    for part in ("1px solid #E5E5EA", "border-radius: 14px"):
        assert part in compare and part in list_box
    assert "background: #FFFFFF" in compare and "background: #FFFFFF" in list_box and "padding: 14px" in compare
    assert "min-height: 682px" in text  # as tall as the results list (10 rows), so the bottom edges line up

    # chart: horizontal rounded bars, room for the labels, no axis numbers and no vertical grid lines
    assert len(at.get("vega_lite_chart")) == 1
    spec = json.loads(at.get("vega_lite_chart")[0].proto.spec)
    enc = spec["encoding"]
    assert spec["mark"]["cornerRadiusEnd"] == 6 and "yOffset" in enc and enc["x"].get("axis") is None
    assert enc["y"]["axis"]["minExtent"] >= 80 and enc["y"]["axis"]["labelLimit"] == 0
    assert '"#A9B8F0"' in json.dumps(spec) and '"#2F49C8"' in json.dumps(spec)
    assert len(list(at.get("column"))) >= 2  # search | country side by side, chart | player


def test_theme_config():
    import tomllib
    from pathlib import Path

    theme = tomllib.loads((Path(APP).parent / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["theme"]
    assert (theme["primaryColor"], theme["backgroundColor"], theme["secondaryBackgroundColor"]) == ("#3B5BDB", "#FFFFFF", "#F6F6F8")
    assert (theme["textColor"], theme["borderColor"]) == ("#222222", "#E5E5EA") and "Noto Sans KR" in theme["font"]


def _tree(at):
    """The page as nested (type, children) so the layout can be checked."""
    def walk(block):
        return [(type(c).__name__ + ":" + getattr(c, "type", ""), walk(c) if hasattr(c, "children") else None)
                for c in block.children.values()]
    return walk(at.main)


def test_wide_layout_rows_and_columns():
    from unittest import mock

    import media
    import streamlit as st

    iframe = mock.patch.object(st, "iframe", wraps=st.iframe)
    with iframe as spy:
        at = _search("Someone Like You", mock.patch.object(media, "covers", return_value={}))
    assert not at.exception
    heights = [c.kwargs.get("height") for c in spy.call_args_list]
    assert heights[0] == 124  # the card is as high as the boxes it lines up with
    assert heights[1] == 682  # the results list: 10 rows of 68px plus the border
    top = _tree(at)
    kinds = [k for k, _ in top]
    # row 1 (title, subtitle) comes first and is full width: plain markdown, no columns around it
    assert kinds[:3] == ["Markdown:markdown"] * 3
    assert 'class="app-title"' in at.markdown[1].value and "다른 나라의 비슷한 노래" in at.markdown[2].value
    # rows 2 and 3 are keyed containers (row2, row3) holding one horizontal block with two columns (3:2)
    rows = [children[0][1] for k, children in top if k == "Block:flex_container" and children
            and children[0][0] == "Block:flex_container" and children[0][1] and children[0][1][0][0] == "Column:column"]
    assert len(rows) == 2
    row2, row3 = rows
    assert [k for k, _ in row2] == ["Column:column"] * 2 and [k for k, _ in row3] == ["Column:column"] * 2
    flat = lambda nodes: [k for k, ch in nodes for k in [k] + (flat(ch) if ch else [])]
    # row 2, left: search + country side by side, then the picker; right: only the card (no player under it)
    assert flat(row2[0][1]) == ["Block:flex_container", "Block:flex_container", "Column:column", "TextInput:text_input",
                                "Caption:caption", "Column:column", "Selectbox:selectbox", "Block:flex_container", "Selectbox:selectbox"]
    assert flat(row2[1][1]) == ["Block:flex_container", "UnknownElement:iframe", "Block:flex_container"]  # card, empty slot
    # row 3, left: heading, list, caption; right: heading, then one box with picker, subtitle, chart, divider, label, player
    assert [k for k, _ in row3[0][1]] == ["Markdown:markdown", "UnknownElement:iframe", "Caption:caption"]
    box = row3[1][1]
    assert box[0][0] == "Markdown:markdown" and box[1][0] == "Block:flex_container"
    assert [k for k, _ in box[1][1]] == ["Selectbox:selectbox", "Markdown:markdown", "UnknownElement:vega_lite_chart",
                                         "Markdown:markdown", "Caption:caption", "UnknownElement:iframe"]
    assert any('class="thin-divider"' in m.value for m in at.markdown)
    assert any(c.value == "1위 곡 미리듣기" for c in at.caption)
    assert not any("내가 고른 곡 듣기" in c.value for c in at.caption)  # the separate player under the card is gone


def _page_css(at=None):
    at = at or AppTest.from_file(APP, default_timeout=120).run()
    return " ".join(m.value for m in at.markdown)


def test_card_lines_up_with_the_inputs_in_css():
    import re

    import results_table as rt

    text = _page_css()
    # the widgets are pinned to the sizes the card is computed from
    assert f".st-key-inputs {{ gap: {rt.ROW_GAP}px; }}" in text
    assert f"height: {rt.LABEL_H}px; min-height: {rt.LABEL_H}px; margin-bottom: {rt.LABEL_GAP}px" in text
    assert f"height: {rt.BOX_H}px; min-height: {rt.BOX_H}px" in text
    assert f".stApp .st-key-mycard {{ margin-top: {rt.CARD_TOP}px; }}" in text  # card top = top of the boxes
    assert not re.search(r"@[A-Z_]+@", text)  # every @NAME@ placeholder was filled in


def test_responsive_rules():
    import re

    text = _page_css()
    wide, phone = re.search(r"@media \(max-width: 1199px\) \{(.*?)\n\}", text, re.S).group(1), re.search(r"@media \(max-width: 640px\) \{(.*?)\n\}", text, re.S).group(1)
    # below 1200px the two main rows (and only those) become one column, in source order
    for row in ("row2", "row3"):
        assert f".stApp .st-key-{row} > div > [data-testid=\"stHorizontalBlock\"]" in wide
        assert f".stApp .st-key-{row} > div > [data-testid=\"stHorizontalBlock\"] > [data-testid=\"stColumn\"]" in wide
    assert "flex-direction: column" in wide and "width: 100% !important" in wide and "min-width: 100% !important" in wide
    assert ".st-key-inputs" not in wide  # the search|country pair is not touched: Streamlit stacks it below 640px
    # stacked: nothing to line up with
    assert ".stApp .st-key-mycard { margin-top: 0; }" in wide and ".stApp .st-key-compare { min-height: 0 !important; }" in wide
    assert "padding-left: 2rem; padding-right: 2rem" in wide  # smaller side padding below 1200px
    assert "padding-left: 1rem; padding-right: 1rem" in phone  # and smaller again on a phone
    # the 3:2 columns on wide screens are Streamlit's own: nothing in the base CSS stacks them
    base = text.split("@media")[0]
    assert "flex-direction: column" not in base.split("/* Responsive")[0].split(".st-key-compare")[0]


def test_page_is_wide_and_set_page_config_comes_first():
    import ast
    from pathlib import Path

    def st_calls(node):  # calls of st.<something> that run when the node runs (function bodies do not)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return []
        found = [node] if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                           and isinstance(node.func.value, ast.Name) and node.func.value.id == "st") else []
        for child in ast.iter_child_nodes(node):
            found += st_calls(child)
        return found

    tree = ast.parse(Path(APP).read_text(encoding="utf-8"))
    first = next(c for stmt in tree.body for c in st_calls(stmt))  # decorators like @st.cache_data are not drawing calls
    assert first.func.attr == "set_page_config"  # the very first Streamlit call that runs
    kwargs = {k.arg: ast.literal_eval(k.value) for k in first.keywords}
    assert kwargs["layout"] == "wide" and kwargs["page_title"] == "Find Similar Songs"


def test_title_only_similar_is_navy():
    text = _page_css()
    assert '<h1 class="app-title" style="color:#222222">Find <span class="accent" style="color:#3B5BDB">Similar</span> Songs</h1>' in text
    assert ".stApp h1.app-title, .stApp h1.app-title * { color: #222222 !important; }" in text
    assert ".stApp h1.app-title span.accent { color: #3B5BDB !important; }" in text
    assert text.count("#3B5BDB") >= 2 and "Find</span>" not in text and "<span>Songs" not in text


def test_picker_shows_only_title_and_artist():
    from unittest import mock

    import media

    at = _search("Someone Like You", mock.patch.object(media, "covers", return_value={}))
    picker = at.selectbox[1]
    assert picker.label.startswith("어떤 곡인가요?")
    assert picker.options[0] == "Someone Like You - Adele"
    assert all("[" not in o and "]" not in o for o in picker.options)  # no genres in square brackets


def _picker(at):
    return next(b for b in at.selectbox if b.label.startswith("어떤 곡인가요?"))


def _online(i, title, artist, isrc="ISRC"):
    return {"id": i, "title": title, "artist": artist, "isrc": isrc, "preview": None, "cover": None, "link": None}


def test_picker_lists_data_songs_first_then_online_ones_without_repeats():
    from unittest import mock

    import media
    import online_lookup

    online = [_online(1, "Someone Like You", "Adele"), _online(2, "Someone Like You (Live)", "A Cover Band")]
    with mock.patch.object(online_lookup, "search_online", return_value=online):
        at = _search("Someone Like You", mock.patch.object(media, "covers", return_value={}))
    assert not at.exception and not at.error
    options = _picker(at).options
    assert options[0] == "Someone Like You - Adele"
    assert options.count("Someone Like You - Adele") == 1  # the online copy of a data song is dropped
    assert options[-1] == "Someone Like You (Live) - A Cover Band (온라인)"
    assert [o.endswith("(온라인)") for o in options] == sorted(o.endswith("(온라인)") for o in options)  # online ones last


def test_online_song_in_the_picker_gets_its_recommendations():
    from unittest import mock

    import media
    import online_lookup

    mood = {f: 0.5 for f in online_lookup.FEATURES}
    mood["tempo"] = 120.0
    online = [_online(7, "Go Hard", "MEOVV", isrc=None)]
    with mock.patch.object(online_lookup, "search_online", return_value=online), \
            mock.patch.object(online_lookup, "resolve_isrc", return_value="KSA002652474") as resolve, \
            mock.patch.object(online_lookup, "fetch_features", return_value=(mood, None)) as fetch:
        at = _search("MEOVV Go Hard Zzzq", mock.patch.object(media, "covers", return_value={}))
    assert not at.exception and not at.error
    assert _picker(at).options == ["Go Hard - MEOVV (온라인)"]
    resolve.assert_called_once_with(7)
    fetch.assert_called_once_with("KSA002652474")
    assert _table_html(at).count('class="row"') == 10


def test_same_search_does_not_call_deezer_twice():
    from unittest import mock

    import media
    import online_lookup

    with mock.patch.object(online_lookup, "search_online", return_value=[_online(1, "X Song", "Y")]) as search, \
            mock.patch.object(media, "covers", return_value={}):
        at = AppTest.from_file(APP, default_timeout=120).run()
        at.text_input[0].set_value("Someone Like You").run()
        at.text_input[0].set_value("  someone   LIKE you ").run()  # same term once normalized
        at.selectbox[0].set_value("Japan").run()  # any other rerun
    assert not at.exception
    assert search.call_count == 1


def test_online_failure_still_shows_data_results_without_an_error():
    from unittest import mock

    import media
    import online_lookup

    for failure in (online_lookup.LookupFailed("timeout"), RuntimeError("boom")):
        with mock.patch.object(online_lookup, "search_online", side_effect=failure):
            at = _search("Someone Like You", mock.patch.object(media, "covers", return_value={}))
        assert not at.exception and not at.error
        assert _picker(at).options[0] == "Someone Like You - Adele"
        assert not any(o.endswith("(온라인)") for o in _picker(at).options)


def test_unknown_song_and_online_failure_offers_the_mood_sliders():
    at = _search("zzqxjv no such song")
    assert not at.exception
    assert any("데이터에도 온라인에도 없어요" in w.value for w in at.warning)
    assert len(at.slider) == 5
