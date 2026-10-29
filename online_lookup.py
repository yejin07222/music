"""Find songs that are not in our dataset: title -> ISRC (Deezer) -> audio features (ReccoBeats).

Both services are free, need no API key and are unofficial/third-party, so
they can be slow, rate limited or down. Every failure is raised as
LookupFailed with a short code; the caller decides what to tell the user.
"""
import concurrent.futures
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from recommender import FEATURES

DEEZER_SEARCH = "https://api.deezer.com/search"
RECCOBEATS = "https://api.reccobeats.com/v1"
USER_AGENT = "MoodMatch-SchoolProject/1.0"  # the default Python UA gets a 403 from ReccoBeats
TIMEOUT_SECONDS = 5
MAX_CHOICES = 5
DEEZER = "https://api.deezer.com"
SEARCH_TIMEOUT_SECONDS = 3  # the picker search must not hold the page up for long
MAX_ARTIST_SONGS = 8
MIN_ARTIST_FANS = 5000  # smaller artists with a famous name are mostly karaoke/tribute acts
MAX_ONLINE = 12


class LookupFailed(Exception):
    """`code` is one of: timeout, network, blocked, rate_limit, not_found, no_results, bad_response."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _get(url, timeout=TIMEOUT_SECONDS):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        code = {403: "blocked", 429: "rate_limit", 404: "not_found"}.get(e.code, "network")
        raise LookupFailed(code) from e
    except TimeoutError as e:
        raise LookupFailed("timeout") from e
    except urllib.error.URLError as e:
        raise LookupFailed("timeout" if isinstance(e.reason, TimeoutError) else "network") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise LookupFailed("bad_response") from e


def search_songs(query):
    """Up to MAX_CHOICES Deezer results as [{"title", "artist", "isrc", "preview", "cover", "link"}].

    `preview` (30 s mp3, signed and valid for only ~15 minutes), `cover` and `link`
    (the track page on deezer.com) may be None.

    Results without an ISRC are skipped, as are repeats of the same ISRC.
    """
    data = _get(f"{DEEZER_SEARCH}?limit=15&q={urllib.parse.quote(query.strip())}")
    if not isinstance(data, dict):
        raise LookupFailed("bad_response")
    if "error" in data:  # Deezer reports quota problems with HTTP 200 + an error body
        err = data["error"]
        raise LookupFailed("rate_limit" if isinstance(err, dict) and err.get("code") == 4 else "bad_response")

    songs, seen = [], set()
    for item in data.get("data", []):
        try:
            isrc = (item.get("isrc") or "").strip().upper()
            if not isrc or isrc in seen:
                continue
            songs.append({
                "title": item["title"], "artist": item["artist"]["name"], "isrc": isrc,
                "preview": item.get("preview") or None,
                "cover": (item.get("album") or {}).get("cover_medium") or None,
                "link": item.get("link") or None,
            })
            seen.add(isrc)
        except (KeyError, TypeError, AttributeError):
            continue
        if len(songs) == MAX_CHOICES:
            break
    if not songs:
        raise LookupFailed("no_results")
    return songs


def _deezer(path):
    """A Deezer API call for the picker search (short timeout). Quota errors arrive as HTTP 200 + an error body."""
    data = _get(f"{DEEZER}{path}", timeout=SEARCH_TIMEOUT_SECONDS)
    if not isinstance(data, dict) or "error" in data:
        raise LookupFailed("bad_response")
    return data.get("data") or []


def _online_song(item, cover=None):
    """One Deezer track object as a picker entry; None if it lacks an id, title or artist.
    `isrc` is None when the object does not carry one (see resolve_isrc)."""
    try:
        return {
            "id": int(item["id"]), "title": item["title"], "artist": item["artist"]["name"],
            "isrc": (item.get("isrc") or "").strip().upper() or None,
            "preview": item.get("preview") or None,
            "cover": cover or (item.get("album") or {}).get("cover_medium") or None,
            "link": item.get("link") or None,
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _artist_songs(query):
    """Popular songs of the Deezer artist named in `query` ("Oasis", or "Go Hard MEOVV": the artist's name
    as whole words anywhere in it; the other words are a title hint, matching songs come first).
    Several artists can share a name and tiny ones are often karaoke/tribute acts, so only artists with at
    least MIN_ARTIST_FANS fans count and the one with the most fans wins. If Deezer has no top list for
    them (e.g. brand-new artists) or it lacks the hinted song, the tracks of their newest albums are used."""
    text = query.strip().casefold()
    found = []
    for a in _deezer(f"/search/artist?limit=10&q={urllib.parse.quote(query.strip())}"):
        name = str(a.get("name", "")).strip().casefold() if isinstance(a, dict) else ""
        m = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) if name else None
        if m and "id" in a and (a.get("nb_fan") or 0) >= MIN_ARTIST_FANS:
            found.append((a["nb_fan"], a["id"], (text[:m.start()] + " " + text[m.end():]).split()))
    if not found:
        return []
    _, artist_id, hint = max(found)

    def matches(song):
        return all(w in song["title"].casefold() for w in hint)

    songs = [s for s in (_online_song(t) for t in _deezer(f"/artist/{artist_id}/top?limit={MAX_ARTIST_SONGS}")) if s]
    if not songs or (hint and not any(matches(s) for s in songs)):
        albums = sorted(_deezer(f"/artist/{artist_id}/albums?limit=20"),
                        key=lambda a: str(a.get("release_date", "")), reverse=True)[:3]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for album, tracks in zip(albums, pool.map(lambda al: _deezer(f"/album/{al['id']}/tracks?limit=10"), albums)):
                songs += [s for s in (_online_song(t, album.get("cover_medium")) for t in tracks) if s]
    songs.sort(key=lambda s: not matches(s))  # stable: the hinted title first, the rest keeps Deezer's order
    return songs[:MAX_ARTIST_SONGS]


def search_online(query):
    """Songs for the picker: the artist's popular songs (if `query` names an artist), then the Deezer title search.

    Returns [{"id", "title", "artist", "isrc" or None, "preview", "cover", "link"}], at most MAX_ONLINE,
    without repeats. The two lookups run side by side and all of it is cut off after SEARCH_TIMEOUT_SECONDS
    in total; a lookup that fails or is too slow only drops its own songs.
    Raises LookupFailed (the first error) if nothing at all could be loaded, or "no_results" if both were empty.
    """
    query = query.strip()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        jobs = [
            pool.submit(_artist_songs, query),
            pool.submit(lambda: [_online_song(t) for t in _deezer(f"/search?limit=15&q={urllib.parse.quote(query)}")]),
        ]
        concurrent.futures.wait(jobs, timeout=SEARCH_TIMEOUT_SECONDS)
        results, error = [], None
        for job in jobs:
            try:
                if not job.done():
                    raise LookupFailed("timeout")
                results.append([s for s in job.result() if s])
            except LookupFailed as e:
                error = error or e
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if error and not any(results):
        raise error
    songs, seen = [], set()
    for song in (s for group in results for s in group):
        key = (song["title"].casefold(), song["artist"].casefold())
        if song["id"] not in seen and key not in seen:
            seen.update({song["id"], key})
            songs.append(song)
    if not songs:
        raise LookupFailed("no_results")
    return songs[:MAX_ONLINE]


def resolve_isrc(track_id):
    """The ISRC of a Deezer track (search lists such as an artist's top songs do not carry it)."""
    data = _get(f"{DEEZER}/track/{int(track_id)}")
    isrc = (data.get("isrc") or "").strip().upper() if isinstance(data, dict) else ""
    if not isrc:
        raise LookupFailed("not_found")
    return isrc


def fetch_features(isrc):
    """Return ({feature: value} for the 9 FEATURES, spotify_track_id or None)."""
    data = _get(f"{RECCOBEATS}/audio-features?ids={urllib.parse.quote(isrc)}")
    content = data.get("content") if isinstance(data, dict) else None
    if not content:
        raise LookupFailed("not_found")
    try:
        features = {f: float(content[0][f]) for f in FEATURES}
    except (KeyError, TypeError, ValueError) as e:
        raise LookupFailed("bad_response") from e
    href = content[0].get("href") or ""
    spotify_id = href.rsplit("/", 1)[-1] if "/track/" in href else None
    return features, spotify_id
