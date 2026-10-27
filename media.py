"""Players and album covers. Nothing is stored: everything is loaded by the browser or
fetched on demand from Spotify (embed, oEmbed) and Deezer (preview, cover).

Every helper fails quietly (returns None) so the rest of the app keeps working.
"""
import concurrent.futures
import html
import json
import re
import threading
import urllib.parse
import urllib.request

SPOTIFY_ID = re.compile(r"[A-Za-z0-9]{22}")
SPOTIFY_EMBED = "https://open.spotify.com/embed/track/{}"
OEMBED = "https://open.spotify.com/oembed?url="
USER_AGENT = "MoodMatch-SchoolProject/1.0"
COVER_TIMEOUT_SECONDS = 3
EMBED_HEIGHT = 152  # Spotify's compact embed
DEEZER_PLAYER_HEIGHT = 110

_DEEZER_HOSTS = ("dzcdn.net", "deezer.com")  # preview and cover hosts we accept
_COVER_HOSTS = ("scdn.co", "spotifycdn.com")


def _https_url_on(url, host_suffixes):
    """The URL if it is https on one of the given hosts (or their subdomains), else None."""
    try:
        parts = urllib.parse.urlparse(url or "")
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in host_suffixes):
        return url
    return None


def spotify_embed_url(track_id):
    return SPOTIFY_EMBED.format(track_id) if SPOTIFY_ID.fullmatch(track_id or "") else None


def deezer_player_html(preview, cover):
    """30-second preview player with the album cover. Both are optional; an element whose
    file fails to load hides itself. None if there is nothing valid to show."""
    preview, cover = _https_url_on(preview, _DEEZER_HOSTS), _https_url_on(cover, _DEEZER_HOSTS)
    if not preview and not cover:
        return None
    hide = "this.style.display='none'"
    img = (
        f'<img src="{html.escape(cover, quote=True)}" width="90" height="90" '
        f'style="border-radius:8px;object-fit:cover" onerror="{hide}">' if cover else ""
    )
    audio = (
        f'<audio controls preload="none" src="{html.escape(preview, quote=True)}" '
        f'style="flex:1;min-width:0" onerror="{hide}"></audio>' if preview else ""
    )
    return (
        '<div style="display:flex;gap:12px;align-items:center;font-family:sans-serif">'
        f"{img}{audio}</div>"
    )


def fetch_cover(track_id):
    """Album cover URL for a Spotify track via the public oEmbed endpoint, or None."""
    if not SPOTIFY_ID.fullmatch(track_id or ""):
        return None
    url = OEMBED + urllib.parse.quote(f"https://open.spotify.com/track/{track_id}", safe="")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=COVER_TIMEOUT_SECONDS) as resp:
            return _https_url_on(json.load(resp).get("thumbnail_url"), _COVER_HOSTS)
    except Exception:  # any network, HTTP or parsing problem just means "no cover"
        return None


_cover_cache, _cover_lock, _CACHE_LIMIT = {}, threading.Lock(), 5000


def covers(track_ids, max_workers=10):
    """{track_id: cover_url or None}; looks the missing ones up in parallel and remembers
    every answer (including failures) until the process restarts."""
    ids = list(dict.fromkeys(track_ids))
    with _cover_lock:
        todo = [i for i in ids if i not in _cover_cache]
    if todo:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(todo))) as pool:
            found = dict(zip(todo, pool.map(fetch_cover, todo)))
        with _cover_lock:
            if len(_cover_cache) + len(found) > _CACHE_LIMIT:
                _cover_cache.clear()
            _cover_cache.update(found)
    with _cover_lock:
        return {i: _cover_cache.get(i) for i in ids}


# --- listen links (plain links, no API) --------------------------------------------------
def _search_text(artists, title):
    first_two = " ".join(a.strip() for a in (artists or "").split(";")[:2] if a.strip())
    return f"{first_two} {title or ''}".strip()


def spotify_track_url(track_id):
    return f"https://open.spotify.com/track/{track_id}" if SPOTIFY_ID.fullmatch(track_id or "") else None


def deezer_track_url(link):
    """Deezer's own track page (from the search result), or None if it does not look right."""
    return _https_url_on(link, ("deezer.com",))


def youtube_search_url(artists, title):
    q = _search_text(artists, title)
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q) if q else None


def listen_links(artists, title, track_id=None, deezer_link=None):
    """[(label, url)] for one song: Spotify for dataset songs (Deezer for songs found
    online), then a YouTube search. Missing ones are left out."""
    first = ("Spotify", spotify_track_url(track_id)) if track_id else ("Deezer", deezer_track_url(deezer_link))
    links = [first, ("YouTube", youtube_search_url(artists, title))]
    return [(label, url) for label, url in links if url]


def links_markdown(links, prefix="듣기: "):
    """Small markdown links (Streamlit opens external links in a new tab); None if there are none."""
    if not links:
        return None
    safe = lambda url: url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    label = lambda text: re.sub(r"([\\\[\]])", r"\\\1", text)
    return prefix + " · ".join(f"[{label(name)}]({safe(url)})" for name, url in links)
