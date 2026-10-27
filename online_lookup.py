"""Find songs that are not in our dataset: title -> ISRC (Deezer) -> audio features (ReccoBeats).

Both services are free, need no API key and are unofficial/third-party, so
they can be slow, rate limited or down. Every failure is raised as
LookupFailed with a short code; the caller decides what to tell the user.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from recommender import FEATURES

DEEZER_SEARCH = "https://api.deezer.com/search"
RECCOBEATS = "https://api.reccobeats.com/v1"
USER_AGENT = "MoodMatch-SchoolProject/1.0"  # the default Python UA gets a 403 from ReccoBeats
TIMEOUT_SECONDS = 5
MAX_CHOICES = 5


class LookupFailed(Exception):
    """`code` is one of: timeout, network, blocked, rate_limit, not_found, no_results, bad_response."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
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
    """Up to MAX_CHOICES Deezer results as [{"title", "artist", "isrc"}].

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
            songs.append({"title": item["title"], "artist": item["artist"]["name"], "isrc": isrc})
            seen.add(isrc)
        except (KeyError, TypeError, AttributeError):
            continue
        if len(songs) == MAX_CHOICES:
            break
    if not songs:
        raise LookupFailed("no_results")
    return songs


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
