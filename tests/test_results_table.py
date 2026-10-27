import re

import results_table as rt

SPOTIFY = "https://open.spotify.com/track/3bNv3VuUOKgrf5hu3YcuRo"
YOUTUBE = "https://www.youtube.com/results?search_query=Adele+Someone+Like+You"
COVER = "https://image-cdn-ak.spotifycdn.com/image/ab67616d00001e02abc"


def row(**kw):
    base = {"title": "Someone Like You", "artist": "Adele", "cover": COVER, "play_url": SPOTIFY,
            "play_label": "Spotify에서 듣기", "youtube_url": YOUTUBE}
    return {**base, **kw}


def test_list_rows_rank_badges_and_buttons():
    html = rt.results_list([row(), row(title="Other"), row(title="Third")])
    assert html.count('class="row"') == 3
    assert re.findall(r'<div class="rank">(\d+)</div>', html) == ["1", "2", "3"]
    assert html.count('class="play"') == 3 and html.count('class="yt"') == 3
    assert html.index('class="yt"') < html.index('class="play"')  # YouTube button first, then the play button
    assert html.count('target="_blank"') == 6 and html.count('rel="noopener noreferrer"') == 6
    assert f'href="{SPOTIFY}"' in html and f'href="{YOUTUBE}"' in html
    assert "듣기</a>" not in html and ">듣기<" not in html and "<th" not in html  # icons only, no text, no header
    assert 'aria-label="Spotify에서 듣기"' in html and 'aria-label="YouTube에서 검색"' in html
    assert html.count("<svg") == 6 and html.count("<circle") == 3  # inline SVG icons: 3 play circles + 3 YouTube marks


def test_design_colors_and_fonts_are_used():
    html = rt.results_list([row()])
    c = rt.COLORS
    assert c["navy"] == "#3B5BDB" and c["navy_light"] == "#E8ECFB" and c["card"] == "#F6F6F8" and c["border"] == "#E5E5EA"
    assert f"background: {c['navy_light']}" in html and f"color: {c['navy']}" in html  # rank badge
    assert "Noto+Sans+KR" in html and "Pretendard" not in html  # the title alone uses Pretendard (in app.py)


def _play_svg(html):
    return re.search(r'<svg class="play-svg".*?</svg>', html, re.S).group(0)


def test_play_button_is_a_white_circle_with_a_rounded_navy_triangle():
    svg = _play_svg(rt.results_list([row()]))
    assert '<circle cx="50" cy="50" r="50" fill="#FFFFFF"/>' in svg  # white circle
    path = re.search(r'<path d="([^"]+)" fill="(#\w+)" stroke="(#\w+)" stroke-width="(\d+)" stroke-linejoin="round"', svg)
    assert path and path.group(2) == path.group(3) == "#3B5BDB"  # fill and stroke are the same navy, round joins
    xs_ys = [tuple(map(float, p)) for p in re.findall(r"[ML]\s*([\d.]+)\s+([\d.]+)", path.group(1))]
    stroke = float(path.group(4))
    height = max(y for _, y in xs_ys) - min(y for _, y in xs_ys) + stroke  # outer height, stroke included
    assert 34 <= height <= 38  # about 36% of the 100-unit circle
    box_center = (min(x for x, _ in xs_ys) + max(x for x, _ in xs_ys)) / 2
    assert 3 <= box_center - 50 <= 5  # shifted right by about 4% of the size
    assert svg.count("<circle") == 1


def test_both_buttons_are_the_same_round_white_button_with_a_thin_border_and_no_shadow():
    html = rt.results_list([row()])
    css = html.split("<style>")[1].split("</style>")[0]
    assert "box-shadow" not in css and "drop-shadow" not in css and "box-shadow" not in rt.song_card(row())
    shared = re.search(r"a\.yt, a\.play \{([^}]*)\}", css).group(1)  # one rule for both buttons
    assert "border: 1px solid #D6D8DF" in shared and "background: #FFFFFF" in shared and "border-radius: 50%" in shared
    for place, size in ((".row", 30), (".song", 40)):  # same size for both buttons, per place
        assert f"{place} a.yt, {place} a.play {{ width: {size}px; height: {size}px; }}" in css
    assert (rt.BUTTON_SIZE_LIST, rt.BUTTON_SIZE_CARD) == (30, 40) and rt.COLORS["button_border"] == "#D6D8DF"


def test_button_icons_fit_inside_the_buttons():
    # the SVG fills the inside of the button (outer size minus the 1px borders); the YouTube mark is smaller
    assert 'width="28" height="28"' in _play_svg(rt.results_list([row()]))
    assert 'width="38" height="38"' in _play_svg(rt.song_card(row()))
    yt = re.search(r'<svg class="yt-svg"[^>]*width="(\d+)" height="(\d+)"', rt.results_list([row()]))
    assert 14 <= int(yt.group(1)) <= 20 and int(yt.group(2)) < int(yt.group(1))
    yt_card = re.search(r'<svg class="yt-svg"[^>]*width="(\d+)"', rt.song_card(row()))
    assert int(yt_card.group(1)) > int(yt.group(1))


def test_my_song_card():
    html = rt.song_card(row())
    assert html.count('class="song"') == 1 and "내가 고른 곡" in html
    assert '<div class="label clip">' in html and '<div class="title clip"' in html and '<div class="artist clip"' in html  # one line each, never wrapped
    assert html.count('class="play"') == 1 and html.count('class="yt"') == 1 and "Someone Like You" in html and "Adele" in html
    assert f'src="{COVER}"' in html
    custom = rt.song_card(row(), label="내가 정한 분위기")
    assert "내가 정한 분위기" in custom and "내가 고른 곡" not in custom


def test_cover_column_is_left_out_when_no_cover_loaded():
    html = rt.results_list([row(cover=None), row(cover="https://evil.example.com/x.jpg")])
    assert "<img" not in html and "nocover" not in html.split("</style>")[1]
    assert 'onerror="this.style.visibility=\'hidden\'"' in rt.results_list([row()])  # a broken cover hides itself
    assert 'class="cover nocover"' in rt.song_card(row(cover=None))  # the card keeps an empty cover box instead


def test_outside_text_and_urls_cannot_inject_markup():
    evil = row(title='<script>alert(1)</script>"><img src=x>', artist="<b>x</b> & y",
               play_url='https://open.spotify.com/track/x" onclick="alert(1)', youtube_url="javascript:alert(1)",
               cover='https://image-cdn-ak.spotifycdn.com/i.jpg" onerror="alert(1)')
    for html in (rt.results_list([evil]), rt.song_card(evil)):
        body = html.split("</style>")[1]
        assert "<script>" not in body and "<b>" not in body and "javascript:" not in body
        assert 'onclick="alert' not in body and 'onerror="alert' not in body
        assert "&lt;script&gt;" in body and "&amp; y" in body
    # links on a foreign host or without https are dropped, the row stays
    html = rt.results_list([row(play_url="https://evil.example.com/a", youtube_url="http://www.youtube.com/results")])
    assert 'class="play"' not in html and 'class="yt"' not in html and html.count('class="row"') == 1


def test_missing_links_leave_the_buttons_out():
    html = rt.results_list([row(play_url=None, youtube_url=None)])
    assert 'class="play"' not in html and 'class="yt"' not in html and '<div class="actions"></div>' in html
    assert 'class="play"' not in rt.song_card(row(play_url=None))


def test_deezer_play_button():
    deezer = rt.song_card(row(play_url="https://www.deezer.com/track/1614228242", play_label="Deezer에서 듣기"))
    assert "https://www.deezer.com/track/1614228242" in deezer and 'aria-label="Deezer에서 듣기"' in deezer
    assert 'src="https://cdn-images.dzcdn.net/images/cover/x.jpg"' in rt.song_card(row(cover="https://cdn-images.dzcdn.net/images/cover/x.jpg"))


def test_heights_fit_the_content():
    assert rt.list_height(10) == 10 * rt.ROW_HEIGHT + 2  # rows plus the 1px border on top and bottom
    assert rt.list_height(3) == 3 * rt.ROW_HEIGHT + 2


def test_card_geometry_lines_up_with_the_input_boxes():
    # the card's top is level with the top of the boxes (below the label) and its bottom with the bottom of the
    # picker box: box + gap + (label + gap + box)
    assert rt.CARD_TOP == rt.LABEL_H + rt.LABEL_GAP == 28
    assert rt.CARD_HEIGHT == rt.BOX_H + rt.ROW_GAP + rt.LABEL_H + rt.LABEL_GAP + rt.BOX_H == 124
    html = rt.song_card(row())
    css = html.split("<style>")[1].split("</style>")[0]
    assert "html, body { margin: 0; height: 100%" in css  # the card fills the whole iframe...
    assert re.search(r"\.song \{ height: 100%;", css)  # ...and so does the card box
    assert "width: 92px; height: 92px" in css  # a larger cover than before (72px)
