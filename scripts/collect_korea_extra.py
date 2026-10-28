"""Collect Korean songs that are not in the Kaggle dataset, with audio features.

Run from the project folder:   python scripts/collect_korea_extra.py
Quick test with a few artists: python scripts/collect_korea_extra.py --limit-artists 5 --no-playlists

Sources (all free, no API keys):
  1. MusicBrainz: every artist registered in South Korea with one of the style tags (indie, hip hop, rock,
     ballad, r&b, folk). 1 request per second, with a proper User-Agent.
  2. Deezer playlists ("korean indie", "한국 인디", ...): their artists are kept only if MusicBrainz confirms
     South Korea or the artist name contains Hangul.
Then, for every artist: Deezer artist -> up to 5 albums -> tracks with ISRC; ReccoBeats gives the 9 audio
features (and the Spotify id, which the app needs for its player) for each ISRC.

Namesakes: Deezer often has artists with exactly the same name as a Korean one (the Danish group "Kandis", the
band KISS vs. a Korean artist "Kiss"). An artist with Hangul in its name or in one of its song titles is accepted.
Every other artist is checked against MusicBrainz's own links: its Deezer page must be the artist we used (if
MusicBrainz links another Deezer page, we switch to that one), or its Spotify artist must be the one ReccoBeats
reports for the songs. If the links point somewhere else the artist is left out. If MusicBrainz has no usable
links, the artist is accepted when most of its ISRCs start with the country code KR (songs released by Korean
labels); otherwise an artist whose name is unique on Deezer is kept and an ambiguous one is left out
(review/korea_extra_rejected_artists.csv lists every artist that was left out and why).

Writes:
  data/korea_extra.csv              the songs (the app adds them to the 한국 pool)
  review/korea_extra_artists.csv    one row per artist, to check by hand
Songs already in data/cleaned.csv and duplicates are skipped. Every network answer is cached in
scripts/.cache/korea_extra/, so an interrupted run continues where it stopped and a rerun is fast.
"""
import argparse
import csv
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = Path(__file__).resolve().parent / ".cache" / "korea_extra"
DATASET = ROOT / "data" / "cleaned.csv"
OUT_SONGS = ROOT / "data" / "korea_extra.csv"
OUT_ARTISTS = ROOT / "review" / "korea_extra_artists.csv"
OUT_REJECTED = ROOT / "review" / "korea_extra_rejected_artists.csv"

USER_AGENT = "MoodMatchSchoolProject/1.0 (https://github.com/yejin07222/music)"  # MusicBrainz wants a contact
MB_TAGS = ["indie", "hip hop", "rock", "ballad", "r&b", "folk"]
PLAYLIST_QUERIES = ["k-indie", "korean indie", "korean hip hop", "k-ballad", "korean rock", "한국 인디",
                    "korean r&b", "korean folk", "한국 힙합", "korean band"]
PLAYLISTS_PER_QUERY = 6
FEATURES = ["valence", "energy", "danceability", "acousticness", "tempo",
            "loudness", "speechiness", "instrumentalness", "liveness"]
COLUMNS = ["track_id", "isrc", "track_name", "artists", "popularity"] + FEATURES + ["genres", "source"]
SPOTIFY_ID = re.compile(r"[A-Za-z0-9]{22}")
HANGUL = re.compile("[ᄀ-ᇿ㄰-㆏가-힣]")

# MusicBrainz tag -> the dataset's genre names, so the app's style bonus (STYLE_FAMILIES) works for these songs.
TAG_MAP = {
    "rock": ["rock"], "hard rock": ["rock"], "classic rock": ["rock"], "pop rock": ["rock"],
    "progressive rock": ["rock"], "psychedelic rock": ["rock"], "garage rock": ["rock"], "post-rock": ["rock"],
    "alternative rock": ["alt-rock"], "alternative": ["alt-rock"], "shoegaze": ["alt-rock"], "post-punk": ["alt-rock"],
    "emo": ["emo"], "indie rock": ["indie", "rock"], "indie": ["indie"], "k-indie": ["indie"], "korean indie": ["indie"],
    "indie pop": ["indie-pop", "indie"], "bedroom pop": ["indie-pop"], "dream pop": ["indie-pop"],
    "punk": ["punk"], "punk rock": ["punk-rock", "punk"], "pop punk": ["punk"],
    "metal": ["metal"], "heavy metal": ["heavy-metal", "metal"],
    "hip hop": ["hip-hop"], "hip-hop": ["hip-hop"], "rap": ["hip-hop"], "trap": ["hip-hop"], "korean hip hop": ["hip-hop"],
    "r&b": ["r-n-b"], "rnb": ["r-n-b"], "contemporary r&b": ["r-n-b"], "rhythm and blues": ["r-n-b"],
    "soul": ["soul"], "neo soul": ["soul", "r-n-b"], "funk": ["funk"],
    "ballad": ["ballad"], "k-ballad": ["ballad"], "korean ballad": ["ballad"],
    "folk": ["folk"], "folk rock": ["folk", "rock"], "folk pop": ["folk"], "singer-songwriter": ["singer-songwriter"],
    "acoustic": ["acoustic"], "country": ["country"],
    "pop": ["pop"], "k-pop": ["k-pop"], "dance": ["dance"], "electronic": ["electronic"], "edm": ["edm"],
    "house": ["house"], "jazz": ["jazz"], "blues": ["blues"],
}
SEARCH_TAG_STYLE = {"indie": "indie", "hip hop": "hip-hop", "rock": "rock", "ballad": "ballad", "r&b": "r-n-b", "folk": "folk"}
PLAYLIST_STYLE = {"k-indie": "indie", "korean indie": "indie", "한국 인디": "indie", "korean hip hop": "hip-hop",
                  "한국 힙합": "hip-hop", "k-ballad": "ballad", "korean rock": "rock", "korean band": "rock",
                  "korean r&b": "r-n-b", "korean folk": "folk"}
MAX_GENRES = 6
KR_ISRC_SHARE_MIN = 0.5


# ----------------------------------------------------------------------------- small pure helpers
def norm(text):
    """Lower-case letters and digits only, single spaces (Hangul is kept)."""
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").casefold()).split())


def has_hangul(text):
    return bool(HANGUL.search(text or ""))


_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")


def title_key(title):
    """A title without (...) / [...] parts and without a ' - Remastered / Live / Ver.' suffix, normalized,
    so that versions of the same song collapse to one."""
    t = _BRACKETS.sub(" ", title or "")
    t = t.split(" - ")[0]
    return norm(t)


_INSTRUMENTAL = re.compile(r"\b(instrumental|inst\.?|karaoke)\b|\(\s*mr\s*\)|-\s*mr\s*$", re.I)


def is_instrumental_title(title):
    return bool(_INSTRUMENTAL.search(title or ""))


def map_genres(search_tags=(), mb_tags=(), playlist_queries=()):
    """Dataset-style genre names (';'-joined by the caller): the style of the search that found the artist
    first (so every song has at least one), then the mapped MusicBrainz tags."""
    out = []
    for t in search_tags:
        if t in SEARCH_TAG_STYLE: out.append(SEARCH_TAG_STYLE[t])
    for q in playlist_queries:
        if q in PLAYLIST_STYLE: out.append(PLAYLIST_STYLE[q])
    for t in mb_tags:
        out += TAG_MAP.get(t.casefold().strip(), [])
    seen, result = set(), []
    for g in out:
        if g not in seen: seen.add(g); result.append(g)
    return result[:MAX_GENRES]


def choose_albums(albums, n):
    """Up to n albums: full albums and EPs before singles and compilations, then the most popular, then the
    newest; one per title."""
    rank = {"album": 0, "ep": 1, "single": 2}
    ordered = sorted(albums, key=lambda a: (rank.get(a.get("record_type"), 3), -(a.get("fans") or 0),
                                            "".join(reversed(a.get("release_date") or ""))))
    seen, out = set(), []
    for a in ordered:
        k = norm(a.get("title"))
        if k in seen: continue
        seen.add(k); out.append(a)
        if len(out) == n: break
    return out


def has_all_features(f):
    """True if `f` has a real number for each of the 9 features (ReccoBeats sometimes answers with nulls)."""
    return bool(f) and all(isinstance(f.get(k), (int, float)) and not isinstance(f.get(k), bool) for k in FEATURES)


def kr_isrc_share(isrcs):
    """Share of the ISRCs that start with the country code KR (released by a Korean label); 0 if there are none.
    Only positive evidence: Korean indie artists who use a foreign distributor have other codes."""
    isrcs = list(isrcs)
    return sum(1 for i in isrcs if (i or "").upper().startswith("KR")) / len(isrcs) if isrcs else 0.0


def safe_cell(value):
    """Spreadsheet-safe text: a leading = - + @ gets a ' in front (as in the other review files)."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "-", "+", "@", "\t", "\r") else s


# ----------------------------------------------------------------------------- HTTP and cache
class Limiter:
    """At most one request every `gap` seconds, across all threads."""

    def __init__(self, gap):
        self.gap, self.lock, self.last = gap, threading.Lock(), 0.0

    def wait(self):
        with self.lock:
            delay = self.last + self.gap - time.monotonic()
            if delay > 0: time.sleep(delay)
            self.last = time.monotonic()


MB_LIMIT, DEEZER_LIMIT, RECCO_LIMIT = Limiter(1.1), Limiter(0.125), Limiter(0.1)  # MusicBrainz: 1 per second


def get_json(url, limiter, retries=4, timeout=30):
    """JSON of `url`, or None if it keeps failing. Backs off on 429/503 and on Deezer's quota error."""
    for attempt in range(retries):
        limiter.wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(2 + 2 * attempt)
            continue
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            time.sleep(1 + attempt)
            continue
        if isinstance(data, dict) and isinstance(data.get("error"), dict):  # Deezer reports errors with HTTP 200
            if data["error"].get("code") == 4:  # quota: wait and retry
                time.sleep(2 + 2 * attempt)
                continue
            return None
        return data
    return None


class Cache:
    """A JSON file per name; thread-safe; saved now and then so a stopped run can continue."""

    def __init__(self, directory, name):
        self.path = Path(directory) / f"{name}.json"
        self.lock, self.dirty = threading.Lock(), 0
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def get(self, key, default=None):
        with self.lock: return self.data.get(key, default)

    def __contains__(self, key):
        with self.lock: return key in self.data

    def put(self, key, value, save_every=25):
        with self.lock:
            self.data[key] = value
            self.dirty += 1
            if self.dirty >= save_every: self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        self.dirty = 0

    def save(self):
        with self.lock: self._save()


# ----------------------------------------------------------------------------- the stages
def mb_artists(tag, cache):
    """All South Korean artists MusicBrainz has with this tag (every page)."""
    if tag in cache: return cache.get(tag)
    found, offset = [], 0
    while True:
        query = urllib.parse.quote(f'country:KR AND tag:"{tag}"')
        data = get_json(f"https://musicbrainz.org/ws/2/artist/?fmt=json&limit=100&offset={offset}&query={query}", MB_LIMIT)
        artists = (data or {}).get("artists", [])
        found += [a for a in artists if a.get("country") == "KR"]
        offset += len(artists)
        if not artists or offset >= (data or {}).get("count", 0): break
    cache.put(tag, found, save_every=1)
    return found


def deezer_exact_matches(name, aliases, cache, key):
    """Every Deezer artist whose name is exactly this name (or an alias): [{id, name, fans}], most fans first."""
    if key in cache: return cache.get(key)
    wanted = {norm(name)} | {norm(a) for a in aliases}
    data = get_json("https://api.deezer.com/search/artist?limit=25&q=" + urllib.parse.quote(name), DEEZER_LIMIT)
    found = [{"id": d["id"], "name": d["name"], "fans": d.get("nb_fan", 0)}
             for d in (data or {}).get("data", []) if norm(d.get("name")) in wanted]
    found.sort(key=lambda d: -d["fans"])
    cache.put(key, found)
    return found


def match_deezer_artist(name, aliases, cache, key):
    """The Deezer artist with exactly this name (or alias), the one with most fans if there are several, plus
    how many there are ("n_exact"); None if there is none."""
    found = deezer_exact_matches(name, aliases, cache, key)
    return {**found[0], "n_exact": len(found)} if found else None


def playlist_artists(queries, cache):
    """{deezer artist id: {"name", "queries": [...]}} from the tracks of the first playlists of each query."""
    result = {}
    for q in queries:
        if q not in cache:
            data = get_json("https://api.deezer.com/search/playlist?limit=12&q=" + urllib.parse.quote(q), DEEZER_LIMIT)
            ids = [p["id"] for p in (data or {}).get("data", []) if 15 <= p.get("nb_tracks", 0) <= 400][:PLAYLISTS_PER_QUERY]
            cache.put(q, ids, save_every=1)
        for pid in cache.get(q):
            key = f"pl{pid}"
            if key not in cache:
                data = get_json(f"https://api.deezer.com/playlist/{pid}/tracks?limit=100", DEEZER_LIMIT)
                cache.put(key, [[t["artist"]["id"], t["artist"]["name"]] for t in (data or {}).get("data", [])])
            for aid, name in cache.get(key):
                result.setdefault(aid, {"name": name, "queries": []})
                if q not in result[aid]["queries"]: result[aid]["queries"].append(q)
    return result


def mb_country(name, cache):
    """'KR' if MusicBrainz has an artist with exactly this name (or alias) registered in South Korea, else the
    country of the match, or 'unknown'. 1 request per second. None if MusicBrainz did not answer (not cached,
    so the artist is asked again later instead of being written off)."""
    if name in cache: return cache.get(name)
    data = get_json("https://musicbrainz.org/ws/2/artist/?fmt=json&limit=5&query=" + urllib.parse.quote(f'artist:"{name}"'), MB_LIMIT)
    if data is None: return None
    wanted, result = norm(name), "unknown"
    for a in (data or {}).get("artists", []):
        if wanted in {norm(a.get("name"))} | {norm(x.get("name")) for x in a.get("aliases", [])}:
            if a.get("country") == "KR" or (a.get("area") or {}).get("name") == "South Korea":
                result = "KR"; break
            result = a.get("country") or "other"
    cache.put(name, result)
    return result


def mb_find_id(name, cache):
    """MusicBrainz id of the South Korean artist with exactly this name (or alias); "" if there is none.
    None if MusicBrainz did not answer (not cached)."""
    if name in cache: return cache.get(name)
    data = get_json("https://musicbrainz.org/ws/2/artist/?fmt=json&limit=5&query=" + urllib.parse.quote(f'artist:"{name}"'), MB_LIMIT)
    if data is None: return None
    wanted, found = norm(name), ""
    for a in data.get("artists", []):
        if wanted in {norm(a.get("name"))} | {norm(x.get("name")) for x in a.get("aliases", [])} and a.get("id") \
                and (a.get("country") == "KR" or (a.get("area") or {}).get("name") == "South Korea"):
            found = a["id"]; break
    cache.put(name, found)
    return found


_DEEZER_ARTIST_URL = re.compile(r"deezer\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?artist/(\d+)")
_SPOTIFY_ARTIST_URL = re.compile(r"open\.spotify\.com/(?:intl-[a-z]+/)?artist/([A-Za-z0-9]{22})")


def mb_url_links(mbid, cache):
    """The Deezer artist id and Spotify artist id MusicBrainz links for this artist:
    {"deezer": int (0 = none), "spotify": str ("" = none)}; None if MusicBrainz did not answer (not cached)."""
    if mbid in cache: return cache.get(mbid)
    data = get_json(f"https://musicbrainz.org/ws/2/artist/{mbid}?fmt=json&inc=url-rels", MB_LIMIT)
    if data is None: return None
    links = {"deezer": 0, "spotify": ""}
    for rel in data.get("relations", []):
        resource = (rel.get("url") or {}).get("resource", "")
        m = _DEEZER_ARTIST_URL.search(resource)
        if m and not links["deezer"]: links["deezer"] = int(m.group(1))
        m = _SPOTIFY_ARTIST_URL.search(resource)
        if m and not links["spotify"]: links["spotify"] = m.group(1)
    cache.put(mbid, links)
    return links


def spotify_artist_ids(isrcs, cache, sample=4):
    """Spotify artist ids ReccoBeats reports for the songs with these ISRCs (a few are enough): a set, or None if
    ReccoBeats knows none of them."""
    ids, missing = set(), [i for i in isrcs[:sample] if i not in cache]
    if missing:
        data = get_json("https://api.reccobeats.com/v1/track?ids=" + ",".join(missing), RECCO_LIMIT)
        got = {}
        for t in (data or {}).get("content", []):
            got[t.get("isrc")] = [m.group(1) for a in t.get("artists", []) for m in [_SPOTIFY_ARTIST_URL.search(a.get("href") or "")] if m]
        for i in missing: cache.put(i, got.get(i, []))
    for i in isrcs[:sample]: ids.update(cache.get(i, []))
    return ids or None


def check_identity(artists, tracks_by_artist, mb_ids, mb_links, recco_artists, workers=2):
    """Decide for every artist whether the Deezer artist is the Korean one (see the top of this file).
    Returns {deezer id: (status, new deezer id or None)}; a status starting with "rejected" means leave it out."""
    def check(item):
        aid, info = item
        ambiguous = info.get("n_exact", 1) > 1
        tracks = tracks_by_artist.get(aid, [])
        if has_hangul(info["name"]) or any(has_hangul(t["title"]) for t in tracks):
            return aid, ("Hangul name or songs", None)

        def no_evidence(why):  # nothing proves or disproves it: Korean ISRC codes count, then the name decides
            if kr_isrc_share(t["isrc"] for t in tracks) >= KR_ISRC_SHARE_MIN:
                return aid, ("ISRC country code KR on most songs", None)
            if ambiguous: return aid, ("rejected: shares its name with other Deezer artists, " + why, None)
            return aid, ("unique name on Deezer, " + why, None)

        mbid = info.get("mb_id") or mb_find_id(info["name"], mb_ids)
        if mbid is None: mbid = mb_find_id(info["name"], mb_ids)  # one more try
        if not mbid: return no_evidence("no MusicBrainz artist found")
        links = mb_url_links(mbid, mb_links)
        if links is None: links = mb_url_links(mbid, mb_links)
        links = links or {"deezer": 0, "spotify": ""}
        if links["deezer"] == aid: return aid, ("MusicBrainz links this Deezer artist", None)
        if links["deezer"]: return aid, ("MusicBrainz links another Deezer artist (switched)", links["deezer"])
        if links["spotify"]:
            seen = spotify_artist_ids([t["isrc"] for t in tracks], recco_artists)
            if seen and links["spotify"] in seen: return aid, ("MusicBrainz links this Spotify artist", None)
            if seen: return aid, ("rejected: MusicBrainz's Spotify artist is not the one on these songs", None)
        return no_evidence("MusicBrainz has no usable link")
    with ThreadPoolExecutor(workers) as pool:
        return dict(pool.map(check, list(artists.items())))


def artist_tracks(deezer_id, max_albums, albums_cache, tracks_cache):
    """Tracks (with ISRC) of the artist's chosen albums: [{isrc, title, artist}]. About 1 + max_albums requests."""
    key = str(deezer_id)
    if key not in albums_cache:
        data = get_json(f"https://api.deezer.com/artist/{deezer_id}/albums?limit=100", DEEZER_LIMIT)
        albums = choose_albums((data or {}).get("data", []), max_albums)
        albums_cache.put(key, [{"id": a["id"], "title": a.get("title")} for a in albums])
    out = []
    for album in albums_cache.get(key):
        akey = str(album["id"])
        if akey not in tracks_cache:
            data = get_json(f"https://api.deezer.com/album/{album['id']}/tracks?limit=100", DEEZER_LIMIT)
            tracks_cache.put(akey, [{"isrc": t["isrc"], "title": t["title"], "artist": t["artist"]["name"], "artist_id": t["artist"]["id"]}
                                    for t in (data or {}).get("data", []) if t.get("isrc")])
        out += [t for t in tracks_cache.get(akey) if t["artist_id"] == deezer_id]
    return out


def fetch_features(isrcs, features_cache):
    """ReccoBeats: {isrc: {spotify_id, popularity, <9 features>}} for the ISRCs it knows (40 per request)."""
    todo = [i for i in isrcs if i not in features_cache]
    batches = [todo[i:i + 40] for i in range(0, len(todo), 40)]

    def one(batch):
        ids = ",".join(batch)
        feats = get_json("https://api.reccobeats.com/v1/audio-features?ids=" + ids, RECCO_LIMIT)
        info = get_json("https://api.reccobeats.com/v1/track?ids=" + ids, RECCO_LIMIT)
        popularity = {t.get("isrc"): t.get("popularity") for t in (info or {}).get("content", [])}
        got = {}
        for f in (feats or {}).get("content", []):
            if "isrc" not in f or not has_all_features(f): continue  # nulls or missing numbers: treat as unavailable
            href = f.get("href") or ""
            got[f["isrc"]] = {"spotify_id": href.rsplit("/", 1)[-1], "popularity": popularity.get(f["isrc"]) or 0,
                              **{k: f[k] for k in FEATURES}}
        for i in batch: features_cache.put(i, got.get(i, False), save_every=200)  # False = not available

    with ThreadPoolExecutor(3) as pool: list(pool.map(one, batches))
    return {i: features_cache.get(i) for i in isrcs if features_cache.get(i)}


def dataset_keys():
    """Spotify ids and (title, artist) keys of the songs that are already in data/cleaned.csv."""
    import pandas as pd
    df = pd.read_csv(DATASET, usecols=["track_id", "track_name", "artists"])
    keys = {(title_key(t), norm(a.split(";")[0])) for t, a in zip(df.track_name, df.artists)}
    return set(df.track_id), keys


def build_rows(artists, tracks_by_artist, features, known_ids, known_keys):
    """The rows for data/korea_extra.csv. `artists`: {id: {name, genres, source, country}}.
    Skips songs without features or Spotify id, with tempo 0, instrumental versions, songs already in the
    dataset and duplicates. Returns (rows, counts_of_what_was_skipped)."""
    rows, skipped = [], Counter()
    seen_ids, seen_isrc, seen_keys = set(), set(), set()
    for aid, tracks in tracks_by_artist.items():
        info = artists[aid]
        candidates = []
        for t in tracks:
            f = features.get(t["isrc"])
            if not has_all_features(f): skipped["no features"] += 1; continue
            if not SPOTIFY_ID.fullmatch(f.get("spotify_id") or ""): skipped["no Spotify id"] += 1; continue
            if f["tempo"] <= 0: skipped["tempo 0"] += 1; continue  # a failed analysis; the dataset drops these rows too
            if is_instrumental_title(t["title"]): skipped["instrumental"] += 1; continue
            candidates.append((t, f))
        candidates.sort(key=lambda tf: -(tf[1].get("popularity") or 0))  # the most popular version of a song wins
        for t, f in candidates:
            key = (title_key(t["title"]), norm(t["artist"]))
            if f["spotify_id"] in known_ids or key in known_keys: skipped["already in the dataset"] += 1; continue
            if f["spotify_id"] in seen_ids or t["isrc"] in seen_isrc or key in seen_keys: skipped["duplicate"] += 1; continue
            seen_ids.add(f["spotify_id"]); seen_isrc.add(t["isrc"]); seen_keys.add(key)
            rows.append({"track_id": f["spotify_id"], "isrc": t["isrc"], "track_name": t["title"], "artists": t["artist"],
                         "popularity": int(f.get("popularity") or 0),
                         **{k: round(float(f[k]), 3) for k in FEATURES},
                         "genres": ";".join(info["genres"]) or "k-pop", "source": info["source"]})
    return rows, skipped


def artist_summary(rows, artists_by_name):
    """One row per artist for review/korea_extra_artists.csv, most songs first. `artists_by_name` is keyed by norm(name)."""
    groups = {}
    for r in rows: groups.setdefault(r["artists"], []).append(r)
    out = []
    for name, rs in groups.items():
        genres = Counter(g for r in rs for g in r["genres"].split(";")).most_common()
        best = max(rs, key=lambda r: r["popularity"])
        out.append({"artist": safe_cell(name), "song_count": len(rs), "genres": ";".join(g for g, _ in genres),
                    "musicbrainz_country": artists_by_name.get(norm(name), {}).get("country", ""), "example_title": safe_cell(best["track_name"]),
                    "identity_check": artists_by_name.get(norm(name), {}).get("identity", ""),
                    "korean_isrc_share": round(kr_isrc_share(r["isrc"] for r in rs), 2)})
    out.sort(key=lambda a: (-a["song_count"], a["artist"]))
    return out


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


# ----------------------------------------------------------------------------- main
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--max-albums", type=int, default=5, help="albums per artist (default 5)")
    p.add_argument("--limit-artists", type=int, help="only the first N MusicBrainz artists (for a quick test)")
    p.add_argument("--no-playlists", action="store_true", help="skip the Deezer playlist artists")
    p.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    p.add_argument("--out", default=str(OUT_SONGS))
    p.add_argument("--review", default=str(OUT_ARTISTS))
    p.add_argument("--rejected", default=str(OUT_REJECTED))
    args = p.parse_args(argv)
    cache_dir = args.cache_dir
    C = {n: Cache(cache_dir, n) for n in ("mb_artists", "deezer_artist2", "playlists", "mb_country", "mb_ids", "mb_links2", "recco_artists", "albums", "tracks", "features")}
    t0 = time.time()
    log = lambda msg: print(f"[{time.time() - t0:6.0f}s] {msg}", flush=True)

    # 1. MusicBrainz: Korean artists with the style tags
    mb = {}
    for tag in MB_TAGS:
        for a in mb_artists(tag, C["mb_artists"]):
            d = mb.setdefault(a["id"], {"mb_id": a["id"], "name": a["name"], "aliases": [x["name"] for x in a.get("aliases", [])],
                                        "tags": [x["name"] for x in a.get("tags", [])], "search_tags": []})
            if tag not in d["search_tags"]: d["search_tags"].append(tag)
    mb_list = list(mb.values())[: args.limit_artists]
    log(f"MusicBrainz: {len(mb)} Korean artists with the tags {MB_TAGS}" + (f" (using the first {len(mb_list)})" if args.limit_artists else ""))

    # 2. Deezer artist for each of them
    artists = {}   # deezer id -> info
    def match(a):
        return a, match_deezer_artist(a["name"], a["aliases"], C["deezer_artist2"], a["mb_id"])
    with ThreadPoolExecutor(4) as pool: matched = list(pool.map(match, mb_list))
    for a, d in matched:
        if d:
            artists[d["id"]] = {"name": d["name"], "genres": map_genres(a["search_tags"], a["tags"]), "country": "KR",
                                "source": "musicbrainz:" + "+".join(a["search_tags"]), "mb_id": a["mb_id"], "n_exact": d["n_exact"]}
    log(f"Deezer: {len(artists)} of {len(mb_list)} MusicBrainz artists found by exact name")

    # 3. playlist artists, kept only if MusicBrainz confirms Korea or the name has Hangul
    verify_future = None
    pool2 = ThreadPoolExecutor(1)
    if not args.no_playlists:
        pl = playlist_artists(PLAYLIST_QUERIES, C["playlists"])
        new = {i: v for i, v in pl.items() if i not in artists}
        log(f"playlists: {len(pl)} artists ({len(new)} not from MusicBrainz)")

        def verify():
            done, lock = [0], threading.Lock()

            def check(item):
                i, v = item
                country = "n/a (Hangul name)" if has_hangul(v["name"]) else mb_country(v["name"], C["mb_country"])
                with lock:
                    done[0] += 1
                    if done[0] % 100 == 0: log(f"  MusicBrainz check: {done[0]}/{len(new)} playlist artists")
                return i, v, country
            # two workers share the 1-request-per-second limiter, so a slow answer does not slow the rest down
            with ThreadPoolExecutor(2) as pool: results = list(pool.map(check, new.items()))
            for n, (i, v, country) in enumerate(results):  # artists MusicBrainz did not answer for: ask once more
                if country is None: results[n] = (i, v, mb_country(v["name"], C["mb_country"]))
            keep = {i: (v, c) for i, v, c in results if c == "KR" or (c or "").startswith("n/a")}
            log(f"  MusicBrainz check done: {len(keep)} of {len(new)} kept, {sum(1 for r in results if r[2] is None)} without an answer")
            return keep
        verify_future = pool2.submit(verify)   # 1 request/second: runs next to the Deezer work below

    # 4. tracks: albums -> ISRC, ReccoBeats features
    tracks_by_artist = {}
    def get_tracks(aid):
        return aid, artist_tracks(aid, args.max_albums, C["albums"], C["tracks"])
    with ThreadPoolExecutor(4) as pool:
        for n, (aid, tr) in enumerate(pool.map(get_tracks, list(artists)), 1):
            tracks_by_artist[aid] = tr
            if n % 100 == 0: log(f"  tracks: {n}/{len(artists)} artists")
    log(f"tracks of the MusicBrainz artists: {sum(len(t) for t in tracks_by_artist.values())}")
    if verify_future:
        keep = verify_future.result()
        for i, (v, country) in keep.items():
            same_name = [d["id"] for d in deezer_exact_matches(v["name"], [], C["deezer_artist2"], "pl:" + v["name"])]
            artists[i] = {"name": v["name"], "genres": map_genres((), (), v["queries"]), "country": country,
                          "source": "playlist:" + "+".join(v["queries"]),
                          "n_exact": len(same_name) if i in same_name else len(same_name) + 1}
        log(f"playlist artists kept: {len(keep)} (MusicBrainz Korea or Hangul name)")
        with ThreadPoolExecutor(4) as pool:
            for aid, tr in pool.map(get_tracks, list(keep)): tracks_by_artist[aid] = tr
    for c in C.values(): c.save()

    # 4b. namesakes: is the Deezer artist really the Korean one? (see the top of this file)
    verdicts = check_identity(artists, tracks_by_artist, C["mb_ids"], C["mb_links2"], C["recco_artists"])
    rejected, switched = [], 0
    for aid, (status, new_id) in verdicts.items():
        info = artists[aid]
        if status.startswith("rejected"):
            rejected.append({"artist": safe_cell(info["name"]), "deezer_id": aid, "reason": status, "source": info["source"],
                             "songs_found": len(tracks_by_artist.get(aid, []))})
            del artists[aid]; tracks_by_artist.pop(aid, None)
        elif new_id:
            switched += 1
            del artists[aid]; old_tracks = tracks_by_artist.pop(aid, None)
            if new_id not in artists:
                artists[new_id] = {**info, "n_exact": 1, "identity": status}
                tracks_by_artist[new_id] = artist_tracks(new_id, args.max_albums, C["albums"], C["tracks"])
        else:
            info["identity"] = status
    log(f"namesake check: {Counter(v[0] for v in verdicts.values())}; {switched} switched, {len(rejected)} left out")
    write_csv(Path(args.rejected), rejected, ["artist", "deezer_id", "reason", "source", "songs_found"])
    for c in C.values(): c.save()
    isrcs = sorted({t["isrc"] for tr in tracks_by_artist.values() for t in tr})
    log(f"audio features for {len(isrcs)} ISRCs ...")
    features = fetch_features(isrcs, C["features"])
    C["features"].save()
    log(f"features found for {len(features)} of {len(isrcs)} ISRCs")

    # 5. rows, files
    known_ids, known_keys = dataset_keys()
    rows, skipped = build_rows(artists, tracks_by_artist, features, known_ids, known_keys)
    write_csv(Path(args.out), rows, COLUMNS)
    by_name = {}
    for info in artists.values(): by_name.setdefault(norm(info["name"]), info)
    summary = artist_summary(rows, by_name)
    write_csv(Path(args.review), summary, ["artist", "song_count", "genres", "musicbrainz_country", "example_title", "identity_check", "korean_isrc_share"])
    log(f"wrote {len(rows)} songs by {len(summary)} artists -> {args.out}")
    log(f"skipped: {dict(skipped)}")
    log("genres: " + str(dict(Counter(g for r in rows for g in r["genres"].split(";")).most_common(12))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
