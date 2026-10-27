"""The results table as a small HTML page (shown with st.iframe).

Streamlit's own table cannot draw round buttons or icons, so this renders the rows itself:
rank, album cover, title, artist, and a round play button plus a YouTube icon that open the
song in a new tab. All colors live in THEMES (one place to restyle); `theme` picks the set.

Everything that comes from outside (titles, artists, URLs) is HTML-escaped and links are
checked, so a strange title or URL cannot add markup.
"""
import html
import urllib.parse

# --- colors: change the look here ------------------------------------------------------
THEMES = {
    "light": {
        "text": "#1f2328", "muted": "#6b7280", "border": "#e5e7eb", "hover": "#f3f4f6",
        "header": "#6b7280", "play": "#1db954", "play_hover": "#17a34a", "play_icon": "#ffffff",
        "cover_bg": "#e5e7eb",
    },
    "dark": {
        "text": "#f0efec", "muted": "#a3a3a3", "border": "#3a3a3a", "hover": "#262730",
        "header": "#a3a3a3", "play": "#1ed760", "play_hover": "#3be477", "play_icon": "#0b0b0b",
        "cover_bg": "#3a3a3a",
    },
}
HEADER_HEIGHT = 40
ROW_HEIGHT = 64
_ALLOWED_LINK_HOSTS = ("open.spotify.com", "deezer.com", "youtube.com")
_ALLOWED_COVER_HOSTS = ("scdn.co", "spotifycdn.com")

_PLAY_SVG = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" fill="currentColor"/></svg>'
_YOUTUBE_SVG = (
    '<svg viewBox="0 0 28 20" width="26" height="19" aria-hidden="true">'
    '<rect width="28" height="20" rx="5" fill="#ff0000"/><path d="M11 5.5v9l8-4.5z" fill="#ffffff"/></svg>'
)


def _safe_link(url, hosts=_ALLOWED_LINK_HOSTS):
    """The URL if it is https on one of the hosts (or a subdomain), else None."""
    try:
        parts = urllib.parse.urlparse(url or "")
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in hosts):
        return url
    return None


def _css(colors):
    c = colors
    return f"""
:root {{ color-scheme: {'dark' if c is THEMES['dark'] else 'light'}; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: "Source Sans", "Source Sans Pro", system-ui, -apple-system, "Segoe UI", "Noto Sans KR", sans-serif;
        font-size: 15px; color: {c['text']}; background: transparent; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
th {{ height: {HEADER_HEIGHT}px; text-align: left; font-weight: 600; font-size: 13px; color: {c['header']};
      border-bottom: 1px solid {c['border']}; padding: 0 8px; }}
td {{ height: {ROW_HEIGHT}px; padding: 0 8px; border-bottom: 1px solid {c['border']}; vertical-align: middle; }}
tr.row:hover td {{ background: {c['hover']}; }}
td.rank {{ width: 48px; color: {c['muted']}; text-align: center; }}
th.rank {{ width: 48px; text-align: center; }}
td.cover, th.cover {{ width: 72px; }}
td.actions, th.actions {{ width: 96px; }}
.cover-img {{ width: 48px; height: 48px; border-radius: 6px; object-fit: cover; display: block; background: {c['cover_bg']}; }}
.cover-empty {{ width: 48px; height: 48px; border-radius: 6px; background: {c['cover_bg']}; }}
.clip {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.title {{ font-weight: 600; }}
.actions-inner {{ display: flex; align-items: center; gap: 12px; }}
a.play {{ width: 34px; height: 34px; border-radius: 50%; background: {c['play']}; color: {c['play_icon']};
          display: inline-flex; align-items: center; justify-content: center; text-decoration: none;
          padding-left: 2px; transition: transform .12s, background .12s; }}
a.play:hover, a.play:focus-visible {{ background: {c['play_hover']}; transform: scale(1.08); outline: none; }}
a.yt {{ display: inline-flex; align-items: center; opacity: .9; transition: transform .12s, opacity .12s; }}
a.yt:hover, a.yt:focus-visible {{ opacity: 1; transform: scale(1.1); outline: none; }}
"""


def _link(url, css_class, label, svg):
    return (
        f'<a class="{css_class}" href="{html.escape(url, quote=True)}" target="_blank" '
        f'rel="noopener noreferrer" title="{html.escape(label, quote=True)}" '
        f'aria-label="{html.escape(label, quote=True)}">{svg}</a>'
    )


def build(rows, theme="light"):
    """HTML page for the results. `rows` is a list of dicts with
    title, artist, cover (url or None), play_url, play_label, youtube_url (urls or None)."""
    colors = THEMES.get(theme, THEMES["light"])
    covers = [_safe_link(r.get("cover"), _ALLOWED_COVER_HOSTS) for r in rows]
    show_cover = any(covers)  # no covers at all (lookup failed): leave the column out
    body = []
    for rank, (row, cover) in enumerate(zip(rows, covers), 1):
        img = (
            f'<img class="cover-img" src="{html.escape(cover, quote=True)}" alt="" loading="lazy" '
            "onerror=\"this.style.visibility='hidden'\">" if cover else '<div class="cover-empty"></div>'
        )
        title, artist = html.escape(row.get("title") or ""), html.escape(row.get("artist") or "")
        actions = []
        play_url = _safe_link(row.get("play_url"))
        if play_url:
            actions.append(_link(play_url, "play", row.get("play_label") or "듣기", _PLAY_SVG))
        yt_url = _safe_link(row.get("youtube_url"))
        if yt_url:
            actions.append(_link(yt_url, "yt", "YouTube에서 검색", _YOUTUBE_SVG))
        body.append(
            f'<tr class="row"><td class="rank">{rank}</td>{f'<td class="cover">{img}</td>' if show_cover else ''}'
            f'<td class="clip title" title="{title}">{title}</td><td class="clip" title="{artist}">{artist}</td>'
            f'<td class="actions"><div class="actions-inner">{"".join(actions)}</div></td></tr>'
        )
    head = (
        f'<tr><th class="rank">순위</th>{'<th class="cover">앨범</th>' if show_cover else ''}<th>제목</th><th>가수</th>'
        '<th class="actions"></th></tr>'  # the last header is intentionally empty
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{_css(colors)}</style></head><body>"
        f"<table><thead>{head}</thead><tbody>{''.join(body)}</tbody></table></body></html>"
    )


def height(n_rows):
    """Iframe height that fits the header and `n_rows` rows."""
    return HEADER_HEIGHT + ROW_HEIGHT * n_rows + 4
