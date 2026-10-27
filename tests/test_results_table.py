import re

import results_table as rt

SPOTIFY = "https://open.spotify.com/track/3bNv3VuUOKgrf5hu3YcuRo"
YOUTUBE = "https://www.youtube.com/results?search_query=Adele+Someone+Like+You"
COVER = "https://image-cdn-ak.spotifycdn.com/image/ab67616d00001e02abc"


def row(**kw):
    base = {"title": "Someone Like You", "artist": "Adele", "cover": COVER, "play_url": SPOTIFY,
            "play_label": "Spotify에서 듣기", "youtube_url": YOUTUBE}
    return {**base, **kw}


def headers(html):
    return re.findall(r"<th[^>]*>([^<]*)</th>", html)


def test_rows_headers_and_links():
    html = rt.build([row(), row(title="Other")], "light")
    assert html.count('class="row"') == 2
    assert headers(html) == ["순위", "앨범", "제목", "가수", ""]  # the actions header has no text
    assert html.count('class="play"') == 2 and html.count('class="yt"') == 2
    assert html.count('target="_blank"') == 4 and html.count('rel="noopener noreferrer"') == 4
    assert f'href="{SPOTIFY}"' in html and f'href="{YOUTUBE}"' in html
    assert "듣기</a>" not in html and ">듣기<" not in html  # no "듣기" text link any more
    assert 'aria-label="Spotify에서 듣기"' in html and 'aria-label="YouTube에서 검색"' in html
    assert "<svg" in html  # icons, not text


def test_cover_column_is_left_out_when_no_cover_loaded():
    html = rt.build([row(cover=None), row(cover="https://evil.example.com/x.jpg")])
    assert headers(html) == ["순위", "제목", "가수", ""] and "<img" not in html
    assert 'onerror="this.style.visibility=\'hidden\'"' in rt.build([row()])  # a broken cover hides itself


def test_outside_text_and_urls_cannot_inject_markup():
    evil = row(title='<script>alert(1)</script>"><img src=x>', artist="<b>x</b> & y",
               play_url='https://open.spotify.com/track/x" onclick="alert(1)', youtube_url="javascript:alert(1)",
               cover='https://image-cdn-ak.spotifycdn.com/i.jpg" onerror="alert(1)')
    html = rt.build([evil])
    assert "<script>" not in html and "<b>" not in html and "javascript:" not in html
    assert 'onclick="alert' not in html and 'onerror="alert' not in html
    assert "&lt;script&gt;" in html and "&amp; y" in html
    # links on a foreign host or without https are dropped, the row stays
    html = rt.build([row(play_url="https://evil.example.com/a", youtube_url="http://www.youtube.com/results")])
    assert 'class="play"' not in html and 'class="yt"' not in html and html.count('class="row"') == 1


def test_missing_links_leave_the_cell_empty_but_valid():
    html = rt.build([row(play_url=None, youtube_url=None)])
    assert 'class="play"' not in html and 'class="yt"' not in html and '<div class="actions-inner"></div>' in html


def test_deezer_play_label_and_themes():
    deezer = rt.build([row(play_url="https://www.deezer.com/track/1614228242", play_label="Deezer에서 듣기")])
    assert "https://www.deezer.com/track/1614228242" in deezer and 'aria-label="Deezer에서 듣기"' in deezer
    light, dark = rt.build([row()], "light"), rt.build([row()], "dark")
    assert rt.THEMES["light"]["play"] in light and rt.THEMES["dark"]["play"] in dark
    assert light != dark and rt.build([row()], "no-such-theme") == light  # unknown theme falls back to light


def test_height_fits_rows():
    assert rt.height(10) == rt.HEADER_HEIGHT + 10 * rt.ROW_HEIGHT + 4
