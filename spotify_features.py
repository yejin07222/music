"""Look up audio features for a Spotify track via the unofficial, free ReccoBeats API.

No API key is needed, but the service is third-party and may be slow, rate
limited or down, so every failure is raised as LookupFailed with a short code
and the caller decides what to tell the user.
"""
import json
import re
import urllib.error
import urllib.request

from recommender import FEATURES

API = "https://api.reccobeats.com/v1"
USER_AGENT = "MoodMatch-SchoolProject/1.0"  # the default Python UA gets a 403
TIMEOUT_SECONDS = 5

_TRACK_RE = re.compile(r"(?:track/|spotify:track:)([A-Za-z0-9]{22})(?![A-Za-z0-9])")
_BARE_ID_RE = re.compile(r"[A-Za-z0-9]{22}")


class LookupFailed(Exception):
    """`code` is one of: timeout, network, blocked, rate_limit, not_found, bad_response."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def extract_track_id(text):
    """Spotify track ID from a link, a `spotify:track:` URI or a bare ID; else None."""
    text = text.strip()
    m = _TRACK_RE.search(text)
    if m:
        return m.group(1)
    return text if _BARE_ID_RE.fullmatch(text) else None


def _get(path):
    req = urllib.request.Request(f"{API}{path}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise LookupFailed("blocked") from e
        if e.code == 429:
            raise LookupFailed("rate_limit") from e
        if e.code == 404:
            raise LookupFailed("not_found") from e
        raise LookupFailed("network") from e
    except TimeoutError as e:
        raise LookupFailed("timeout") from e
    except urllib.error.URLError as e:
        raise LookupFailed("timeout" if isinstance(e.reason, TimeoutError) else "network") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise LookupFailed("bad_response") from e


def fetch_features(track_id):
    """Return ({feature: value} for the 9 FEATURES, "title - artists" or None)."""
    data = _get(f"/audio-features?ids={track_id}")
    content = data.get("content") if isinstance(data, dict) else None
    if not content:
        raise LookupFailed("not_found")
    try:
        features = {f: float(content[0][f]) for f in FEATURES}
    except (KeyError, TypeError, ValueError) as e:
        raise LookupFailed("bad_response") from e

    title = None  # nice to have; never fails the lookup
    try:
        info = _get(f"/track?ids={track_id}")["content"][0]
        artists = ", ".join(a["name"] for a in info["artists"])
        title = f"{info['trackTitle']} - {artists}"
    except (LookupFailed, KeyError, IndexError, TypeError):
        pass
    return features, title
