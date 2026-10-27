"""The song card and the results list, as small HTML pages shown with st.iframe.

Streamlit's own widgets cannot draw rank badges, round play buttons or icons, so these two
parts are rendered here. All colors live in COLORS (one place to restyle). Everything that
comes from outside (titles, artists, URLs) is HTML-escaped and links/covers are checked on
an allow-list of hosts, so a strange title or URL cannot add markup.
"""
import html
import urllib.parse

# --- colors: change the look here ------------------------------------------------------
COLORS = {
    "bg": "#FFFFFF", "card": "#F6F6F8", "border": "#E5E5EA", "separator": "#EEEEF2",
    "text": "#222222", "muted": "#777777",
    "navy": "#3B5BDB", "navy_light": "#E8ECFB",
    "button_border": "#D6D8DF", "button_hover": "#F6F6F8",
}
FONT_URL = "https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap"
FONT_STACK = '"Noto Sans KR", system-ui, -apple-system, "Segoe UI", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif'

BUTTON_SIZE_LIST, BUTTON_SIZE_CARD = 30, 40  # diameter of the round buttons (play and YouTube), in px
ROW_HEIGHT = 68    # one result row, separator included

# Sizes of the input area on the left of the second row. app.py pins Streamlit's widgets to exactly these
# values in CSS, and the "my song" card on the right is sized and offset from them, so that its top edge
# is level with the top of the search/country boxes and its bottom edge with the bottom of the picker box.
LABEL_H, LABEL_GAP, BOX_H, ROW_GAP = 24, 4, 40, 16   # label height, label-to-box gap, input box height, gap between rows
CARD_TOP = LABEL_H + LABEL_GAP                        # 28: from the top of the left column to the top of the boxes
CARD_HEIGHT = BOX_H + ROW_GAP + LABEL_H + LABEL_GAP + BOX_H  # 124: top of the search box to the bottom of the picker box
_ALLOWED_LINK_HOSTS = ("open.spotify.com", "deezer.com", "youtube.com")
_ALLOWED_COVER_HOSTS = ("scdn.co", "spotifycdn.com", "dzcdn.net", "deezer.com")



def _play_svg(size):
    """White circle with a navy triangle, drawn inside a round button with a thin border. The triangle
    is about 36% of the circle high (30 units of path plus the 6-unit stroke, in a 100-unit circle), has
    rounded corners (stroke of the same color with round joins) and sits ~4% of the size right of the
    center so it looks centered. `size` is the button's outer diameter; the SVG fills the inside."""
    navy, inner = COLORS["navy"], size - 2  # minus the 1px border on each side
    return (
        f'<svg class="play-svg" viewBox="0 0 100 100" width="{inner}" height="{inner}" aria-hidden="true">'
        '<circle cx="50" cy="50" r="50" fill="#FFFFFF"/>'
        f'<path d="M41 35 L67 50 L41 65 Z" fill="{navy}" stroke="{navy}" stroke-width="6" '
        'stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def _youtube_svg(size):
    """The YouTube mark, about 58% of the button's diameter wide."""
    w = round(size * 0.58)
    return (
        f'<svg class="yt-svg" viewBox="0 0 28 20" width="{w}" height="{round(w * 20 / 28)}" aria-hidden="true">'
        '<rect width="28" height="20" rx="5" fill="#ff0000"/><path d="M11 5.5v9l8-4.5z" fill="#ffffff"/></svg>'
    )


def _safe_url(url, hosts):
    """The URL if it is https on one of the hosts (or a subdomain), else None."""
    try:
        parts = urllib.parse.urlparse(url or "")
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in hosts):
        return url
    return None


def _css():
    c = COLORS
    return f"""
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; height: 100%; overflow: hidden; background: transparent; }}
body {{ font-family: {FONT_STACK}; color: {c['text']}; font-size: 15px; }}
.clip {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.cover {{ border-radius: 10px; object-fit: cover; flex: none; background: {c['border']}; display: block; }}
.title {{ font-weight: 500; color: {c['text']}; }}
.artist {{ font-size: 13px; color: {c['muted']}; margin-top: 2px; }}
.text {{ flex: 1; min-width: 0; }}
.actions {{ display: flex; align-items: center; gap: 10px; flex: none; }}
a {{ text-decoration: none; }}
a.yt, a.play {{ border-radius: 50%; border: 1px solid {c['button_border']}; background: #FFFFFF;
               display: inline-flex; align-items: center; justify-content: center; transition: background .12s; }}
a.yt:hover, a.yt:focus-visible, a.play:hover, a.play:focus-visible {{ background: {c['button_hover']}; outline: none; }}
.row a.yt, .row a.play {{ width: {BUTTON_SIZE_LIST}px; height: {BUTTON_SIZE_LIST}px; }}
.song a.yt, .song a.play {{ width: {BUTTON_SIZE_CARD}px; height: {BUTTON_SIZE_CARD}px; }}
.play-svg, .yt-svg {{ display: block; }}
/* results list */
.list {{ border: 1px solid {c['border']}; border-radius: 14px; background: {c['bg']}; overflow: hidden; }}
.row {{ height: {ROW_HEIGHT}px; display: flex; align-items: center; gap: 14px; padding: 0 14px; border-bottom: 1px solid {c['separator']}; }}
.row:last-child {{ border-bottom: 0; }}
.row:hover {{ background: {c['card']}; }}
.rank {{ width: 28px; height: 28px; border-radius: 8px; background: {c['navy_light']}; color: {c['navy']}; font-size: 13px; font-weight: 700;
         display: flex; align-items: center; justify-content: center; flex: none; }}
.row .cover, .row .nocover {{ width: 48px; height: 48px; }}
/* my song card: fills the whole iframe, which has the height of the boxes it is aligned with */
.song {{ height: 100%; display: flex; align-items: center; gap: 16px; padding: 0 16px; background: {c['card']};
         border: 1px solid {c['border']}; border-radius: 14px; }}
.song .cover, .song .nocover {{ width: 92px; height: 92px; border-radius: 12px; }}
.song .label {{ font-size: 12px; color: {c['muted']}; margin-bottom: 3px; }}
.song .title {{ font-size: 19px; font-weight: 700; line-height: 1.25; }}
.song .artist {{ font-size: 14px; margin-top: 3px; }}
@media (max-width: 420px) {{ .song {{ gap: 12px; padding: 0 12px; }} .song .cover, .song .nocover {{ width: 72px; height: 72px; }}
                           .song .title {{ font-size: 17px; }} }}
"""


def _page(body):
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link rel="stylesheet" href="{FONT_URL}"><style>{_css()}</style></head><body>{body}</body></html>'
    )


def _link(url, css_class, label, svg):
    return (
        f'<a class="{css_class}" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" '
        f'title="{html.escape(label, quote=True)}" aria-label="{html.escape(label, quote=True)}">{svg}</a>'
    )


def _buttons(song, size=BUTTON_SIZE_LIST):
    """YouTube button and play button for one song (each left out if its link is missing)."""
    out = []
    yt = _safe_url(song.get("youtube_url"), _ALLOWED_LINK_HOSTS)
    if yt:
        out.append(_link(yt, "yt", "YouTube에서 검색", _youtube_svg(size)))
    play = _safe_url(song.get("play_url"), _ALLOWED_LINK_HOSTS)
    if play:
        out.append(_link(play, "play", song.get("play_label") or "재생", _play_svg(size)))
    return "".join(out)


def _cover_img(url):
    url = _safe_url(url, _ALLOWED_COVER_HOSTS)
    if not url:
        return '<div class="cover nocover"></div>'
    return (f'<img class="cover" src="{html.escape(url, quote=True)}" alt="" loading="lazy" '
            "onerror=\"this.style.visibility='hidden'\">")


def results_list(rows):
    """The ranked list. `rows`: dicts with title, artist, cover, play_url, play_label, youtube_url
    (urls may be None). The cover column is left out when no row has a usable cover."""
    show_cover = any(_safe_url(r.get("cover"), _ALLOWED_COVER_HOSTS) for r in rows)
    items = []
    for rank, row in enumerate(rows, 1):
        title, artist = html.escape(row.get("title") or ""), html.escape(row.get("artist") or "")
        items.append(
            f'<div class="row"><div class="rank">{rank}</div>{_cover_img(row.get("cover")) if show_cover else ""}'
            f'<div class="text"><div class="title clip" title="{title}">{title}</div>'
            f'<div class="artist clip" title="{artist}">{artist}</div></div>'
            f'<div class="actions">{_buttons(row)}</div></div>'
        )
    return _page(f'<div class="list">{"".join(items)}</div>')


def song_card(song, label="내가 고른 곡"):
    """The card for the song the user picked: cover, label, title, artist, and on the right the
    buttons (a filled navy play button). `song` has the same keys as a row of the list."""
    title, artist = html.escape(song.get("title") or ""), html.escape(song.get("artist") or "")
    return _page(
        f'<div class="song">{_cover_img(song.get("cover"))}<div class="text"><div class="label clip">{html.escape(label)}</div>'
        f'<div class="title clip" title="{title}">{title}</div><div class="artist clip" title="{artist}">{artist}</div></div>'
        f'<div class="actions">{_buttons(song, BUTTON_SIZE_CARD)}</div></div>'
    )


def list_height(n_rows):
    """Iframe height of the list: the rows plus the 1px border on top and bottom."""
    return ROW_HEIGHT * n_rows + 2
