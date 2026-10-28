"""Apply the hand decisions in review/korea_artist_review.csv to data/korea_extra.csv.

Run after scripts/collect_korea_extra.py:   python scripts/apply_korea_review.py

Columns of the review file: artist, list (kept = the artist is in data/korea_extra.csv, rejected = it was left
out by the collection), decision, reason. What each decision does:
  remove               drop the artist's songs from the file
  check (kept list)    keep the artist only if its songs are clearly Korean: for at least half of the songs the
                       ISRC starts with KR, or the title/artist has Hangul, or the song features an artist with a
                       Hangul name; otherwise drop it
  rescue, check        (rejected list) find the Korean artist on Deezer: the Hangul names (MusicBrainz aliases and
                       review/korea_artist_korean_names.csv) and the name are searched on Deezer, every exact-name
                       page (up to 8) is looked at, and the best page is used if at least half of its songs have
                       a KR ISRC or a Hangul title (and the same holds for the songs that end up in the file, i.e. the
                       ones with audio features); its songs are then added. Nothing is added if no page can be
                       verified; the report says what the best page looked like.
  keep, keep_out, already_in   nothing
Explicit overrides (review/korea_artist_overrides.csv: artist, mode, pages, note) are applied instead of the rule for
the artists they name:
  mode page      all songs of the given Deezer page(s) (pages = ids separated by spaces)
  mode kr_isrc   from every exact-name Deezer page of the artist (up to 12), only the songs with a KR ISRC
Network answers are cached (scripts/.cache/korea_extra/), like in the collection script.
"""
import argparse
import importlib.util
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("collect_korea_extra", HERE / "collect_korea_extra.py")
cke = importlib.util.module_from_spec(spec)
sys.modules["collect_korea_extra"] = cke
spec.loader.exec_module(cke)

ROOT = cke.ROOT
REVIEW = ROOT / "review" / "korea_artist_review.csv"
EVIDENCE_MIN = 0.5      # share of songs that must show the artist is Korean
MIN_SONGS = 1           # a Deezer page with no songs cannot be verified (pages of Korean-named artists are often tiny)
MAX_PAGES = 8           # Deezer pages with the same name looked at per artist
KOREAN_NAMES = ROOT / "review" / "korea_artist_korean_names.csv"   # artist, korean_name: extra search names
OVERRIDES = ROOT / "review" / "korea_artist_overrides.csv"          # artist, mode, pages, note: explicit decisions
OVERRIDE_PAGES = 12     # exact-name pages looked at in mode kr_isrc
_FEAT = re.compile(r"\b(feat\.?|featuring|ft\.?|with)\b", re.I)


def korean_song(title, artist, isrc):
    """True if there is a sign that this song is Korean: a KR ISRC, Hangul in the title or artist, or a credited
    featured artist with a Hangul name (e.g. "Song (Feat. 윤하)")."""
    if (isrc or "").upper().startswith("KR"): return True
    if cke.has_hangul(title) or cke.has_hangul(artist): return True
    return bool(_FEAT.search(title or "")) and cke.has_hangul(title)


def korean_share(songs):
    """Share of songs with a sign of being Korean; songs = [(title, artist, isrc)]. 0 if there are none."""
    songs = list(songs)
    return sum(1 for t, a, i in songs if korean_song(t, a, i)) / len(songs) if songs else 0.0


def load_korean_names(path):
    """{norm(artist): [Hangul names]} from the extra-names file (it may be missing)."""
    if not Path(path).exists(): return {}
    d = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    out = {}
    for a, k in zip(d.artist, d.korean_name):
        if k.strip(): out.setdefault(cke.norm(a), []).append(k.strip())
    return out


def load_overrides(path):
    """[{artist, key, mode, pages: [ids], note}] from the overrides file (it may be missing)."""
    if not Path(path).exists(): return []
    d = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    out = []
    for _, r in d.iterrows():
        mode = r["mode"].strip()
        if mode not in ("page", "kr_isrc"): raise ValueError(f"unknown override mode {mode!r} for {r['artist']}")
        pages = [int(x) for x in r["pages"].split()]
        if mode == "page" and not pages: raise ValueError(f"override {r['artist']}: mode page needs page ids")
        out.append({"artist": r["artist"].strip(), "key": cke.norm(r["artist"]), "mode": mode, "pages": pages, "note": r["note"]})
    return out


def load_decisions(path):
    d = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    for col in ("artist", "list", "decision"):
        d[col] = d[col].str.strip()
    d["key"] = d["artist"].map(cke.norm)
    return d


def hangul_aliases(name, mb_artists_cache, mb_ids_cache, aliases_cache):
    """Hangul names MusicBrainz knows for the artist (aliases), found by MusicBrainz id."""
    key = cke.norm(name)
    for tag_list in mb_artists_cache.data.values():
        for a in tag_list:
            if cke.norm(a.get("name")) == key:
                return [x["name"] for x in a.get("aliases", []) if cke.has_hangul(x["name"])], a["id"]
    mbid = mb_ids_cache.get(name) or cke.mb_find_id(name, mb_ids_cache)
    if not mbid: return [], None
    if mbid not in aliases_cache:
        data = cke.get_json(f"https://musicbrainz.org/ws/2/artist/{mbid}?fmt=json&inc=aliases", cke.MB_LIMIT)
        if data is None: return [], mbid
        aliases_cache.put(mbid, [x["name"] for x in data.get("aliases", []) if cke.has_hangul(x["name"])] +
                          ([data["name"]] if cke.has_hangul(data.get("name", "")) else []))
    return aliases_cache.get(mbid), mbid


def find_pages(names, exclude_id, deezer_cache):
    """Deezer artists whose name is exactly one of `names`: [{id, name, fans}], most fans first, at most MAX_PAGES."""
    seen, pages = set(), []
    for n in names:
        for d in cke.deezer_exact_matches(n, [], deezer_cache, "review:" + n):
            if d["id"] not in seen and d["id"] != exclude_id:
                seen.add(d["id"]); pages.append(d)
    return sorted(pages, key=lambda d: -d["fans"])[:MAX_PAGES]


def best_page(pages, max_albums, caches):
    """The page whose songs look most Korean (at least EVIDENCE_MIN, at least MIN_SONGS songs).
    Returns (page, tracks, share) or None, and a list of short descriptions of every page looked at."""
    best, seen = None, []
    for p in pages:
        tracks = cke.artist_tracks(p["id"], max_albums, caches["albums"], caches["tracks"])
        share = korean_share((t["title"], t["artist"], t["isrc"]) for t in tracks)
        seen.append(f"'{p['name']}' id {p['id']} ({p['fans']} fans): {len(tracks)} songs, {share:.0%} Korean")
        if len(tracks) < MIN_SONGS: continue
        if share >= EVIDENCE_MIN and (best is None or (share, len(tracks)) > (best[2], len(best[1]))):
            best = (p, tracks, share)
    return best, seen


def genres_from_source(source):
    kind, _, rest = (source or "").partition(":")
    parts = [x for x in rest.split("+") if x]
    return cke.map_genres(parts if kind == "musicbrainz" else (), (), parts if kind == "playlist" else ())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--review", default=str(REVIEW))
    p.add_argument("--korean-names", default=str(KOREAN_NAMES))
    p.add_argument("--overrides", default=str(OVERRIDES))
    p.add_argument("--songs", default=str(cke.OUT_SONGS))
    p.add_argument("--artists-file", default=str(cke.OUT_ARTISTS))
    p.add_argument("--rejected-file", default=str(cke.OUT_REJECTED))
    p.add_argument("--cache-dir", default=str(cke.DEFAULT_CACHE))
    p.add_argument("--max-albums", type=int, default=5)
    args = p.parse_args(argv)

    caches = {n: cke.Cache(args.cache_dir, n) for n in ("mb_artists", "mb_ids", "mb_aliases", "deezer_artist2", "albums", "tracks", "features")}
    decisions = load_decisions(args.review)
    extra_names = load_korean_names(args.korean_names)
    overrides = load_overrides(args.overrides)
    override_keys = {o["key"] for o in overrides}
    songs = pd.read_csv(args.songs)
    songs["key"] = songs["artists"].map(cke.norm)
    rejected = pd.read_csv(args.rejected_file) if Path(args.rejected_file).exists() else pd.DataFrame(columns=["artist", "deezer_id", "reason", "source", "songs_found"])
    rejected["key"] = rejected["artist"].astype(str).str.lstrip("'").map(cke.norm)
    report = []   # (group, artist, songs, note)

    # 1. remove
    remove = set(decisions[(decisions.list == "kept") & (decisions.decision == "remove")].key)
    for key in remove:
        n = int((songs.key == key).sum())
        name = decisions[decisions.key == key].artist.iloc[0]
        report.append(("removed", name, n, "decision: remove" if n else "not in the file"))
    songs = songs[~songs.key.isin(remove)]

    # 2. check (kept list): keep only clearly Korean artists
    for key in decisions[(decisions.list == "kept") & (decisions.decision == "check")].key:
        rows = songs[songs.key == key]
        name = decisions[decisions.key == key].artist.iloc[0]
        if rows.empty: report.append(("not found", name, 0, "not in the file")); continue
        share = korean_share(zip(rows.track_name, rows.artists, rows.isrc))
        if share >= EVIDENCE_MIN:
            report.append(("kept after check", name, len(rows), f"{share:.0%} of the songs look Korean"))
        else:
            report.append(("dropped after check", name, len(rows), f"{share:.0%} of the songs look Korean (needs {EVIDENCE_MIN:.0%})"))
            songs = songs[songs.key != key]

    # 3. rescue / check (rejected list): find the Korean Deezer page
    known_ids, known_keys = cke.dataset_keys()
    new_rows, new_artists = [], {}
    todo = decisions[(decisions.list == "rejected") & decisions.decision.isin(["rescue", "check"]) & ~decisions.key.isin(override_keys)]
    for o in overrides:
        old = rejected[rejected.key == o["key"]]
        source = old.source.iloc[0] if len(old) else ""
        done = songs[songs.source.astype(str).str.startswith("review-override") & (songs.key == o["key"])]
        if len(done):
            report.append(("already added (override)", o["artist"], len(done), "songs are already in the file")); continue
        if o["mode"] == "page":
            pages = [{"id": i, "name": o["artist"], "fans": 0} for i in o["pages"]]
        else:
            pages = find_pages([o["artist"]], None, caches["deezer_artist2"])[:OVERRIDE_PAGES]
        by_page = {pg["id"]: cke.artist_tracks(pg["id"], args.max_albums, caches["albums"], caches["tracks"]) for pg in pages}
        if o["mode"] == "kr_isrc":
            by_page = {i: [t for t in tr if t["isrc"].upper().startswith("KR")] for i, tr in by_page.items()}
        found_songs = sum(len(tr) for tr in by_page.values())
        label = "all songs of page" if o["mode"] == "page" else "only songs with a KR ISRC, from"
        pages_text = ", ".join(f"{pg['id']}" for pg in pages) or "none"
        if not found_songs:
            report.append(("override: nothing to add", o["artist"], 0, f"{o['mode']}: no song found on {len(pages)} page(s) ({pages_text})")); continue
        isrcs = sorted({t["isrc"] for tr in by_page.values() for t in tr})
        features = cke.fetch_features(isrcs, caches["features"]); caches["features"].save()
        info = {"name": o["artist"], "genres": genres_from_source(source), "country": "KR", "source": f"review-override:{o['mode']}",
                "identity": f"explicit override ({label} Deezer page {pages_text}): {o['note']}"}
        existing = {(cke.title_key(t), cke.norm(a.split(";")[0])) for t, a in zip(songs.track_name, songs.artists)}
        rows, _ = cke.build_rows({i: info for i in by_page}, by_page, features, known_ids | set(songs.track_id) | {r["track_id"] for r in new_rows},
                                 known_keys | existing | {(cke.title_key(r["track_name"]), cke.norm(r["artists"])) for r in new_rows})
        if rows:
            new_rows += rows; new_artists[o["key"]] = info
            report.append(("override added", o["artist"], len(rows), f"{o['mode']}: {found_songs} candidate songs on {len(pages)} page(s) ({pages_text})"))
        else:
            report.append(("override: nothing to add", o["artist"], 0, f"{o['mode']}: {found_songs} candidate songs, none new with audio features"))

    for _, dec in todo.iterrows():
        old = rejected[rejected.key == dec.key]
        old_id, source = (int(old.deezer_id.iloc[0]), old.source.iloc[0]) if len(old) else (None, "")
        aliases, mbid = hangul_aliases(dec.artist, caches["mb_artists"], caches["mb_ids"], caches["mb_aliases"])
        names = list(dict.fromkeys(aliases + extra_names.get(dec.key, []) + [dec.artist]))
        done = songs[songs.source.astype(str).str.startswith("review-rescue") & songs.key.isin({cke.norm(n) for n in names})]
        if len(done):  # rescued by an earlier run: nothing to do (and nothing to ask the network)
            report.append(("already rescued", dec.artist, len(done), "songs are already in the file"))
            continue
        pages = find_pages(names, old_id, caches["deezer_artist2"])
        found, seen = best_page(pages, args.max_albums, caches)
        if not found:
            looked = "; ".join(seen) if seen else "no Deezer page with these names"
            report.append(("still unverified", dec.artist, int(old.songs_found.iloc[0]) if len(old) else 0,
                           f"searched {', '.join(names)}: {looked}"))
            continue
        page, tracks, share = found
        isrcs = sorted({t["isrc"] for t in tracks})
        features = cke.fetch_features(isrcs, caches["features"])
        caches["features"].save()
        info = {"name": page["name"], "genres": genres_from_source(source), "country": "KR", "source": "review-rescue:" + (source or dec.decision),
                "identity": f"found by review: Deezer page '{page['name']}' ({share:.0%} of its songs have a KR ISRC or Hangul)"}
        existing = {(cke.title_key(t), cke.norm(a.split(";")[0])) for t, a in zip(songs.track_name, songs.artists)}
        rows, _ = cke.build_rows({page["id"]: info}, {page["id"]: tracks}, features, known_ids | set(songs.track_id) | {r["track_id"] for r in new_rows},
                                 known_keys | existing | {(cke.title_key(r["track_name"]), cke.norm(r["artists"])) for r in new_rows})
        added_share = korean_share((r["track_name"], r["artists"], r["isrc"]) for r in rows)
        if rows and added_share < EVIDENCE_MIN:  # the rule is about the songs that are added, not the whole page
            report.append(("still unverified", dec.artist, 0, f"page '{page['name']}' id {page['id']} passed ({share:.0%}) but only "
                           f"{added_share:.0%} of its {len(rows)} songs with audio features look Korean"))
        elif rows:
            new_rows += rows; new_artists[cke.norm(page["name"])] = info
            report.append(("rescued", dec.artist, len(rows), f"Deezer page '{page['name']}' id {page['id']}, {share:.0%} Korean evidence"))
        else:
            report.append(("still unverified", dec.artist, 0, f"page '{page['name']}' verified but no new songs with features"))

    # 4. write
    final = pd.concat([songs.drop(columns="key"), pd.DataFrame(new_rows, columns=cke.COLUMNS)], ignore_index=True)
    final = final[cke.COLUMNS]
    cke.write_csv(Path(args.songs), final.to_dict("records"), cke.COLUMNS)
    # artist file: keep the old rows of artists that are still there, add the rescued ones
    old_artists = pd.read_csv(args.artists_file, dtype=str, keep_default_na=False) if Path(args.artists_file).exists() else pd.DataFrame()
    by_name = {cke.norm(n): i for n, i in new_artists.items()}
    summary = cke.artist_summary(final.to_dict("records"), {k: {"country": "KR", "identity": v["identity"]} for k, v in by_name.items()})
    if len(old_artists):
        old = old_artists.assign(key=old_artists.artist.str.lstrip("'").map(cke.norm)).set_index("key")
        for row in summary:
            k = cke.norm(row["artist"].lstrip("'"))
            if k in old.index and k not in by_name:
                row["musicbrainz_country"] = old.loc[k, "musicbrainz_country"]; row["identity_check"] = old.loc[k, "identity_check"]
    cke.write_csv(Path(args.artists_file), summary, ["artist", "song_count", "genres", "musicbrainz_country", "example_title", "identity_check", "korean_isrc_share"])
    rescued_keys = {cke.norm(r[1]) for r in report if r[0] in ("rescued", "override added")}
    rejected[~rejected.key.isin(rescued_keys)].drop(columns="key").to_csv(args.rejected_file, index=False, encoding="utf-8")
    for c in caches.values(): c.save()

    print("\n=== report ===")
    for group in ("removed", "dropped after check", "kept after check", "rescued", "already rescued", "override added",
                  "already added (override)", "override: nothing to add", "still unverified", "not found"):
        rows = [r for r in report if r[0] == group]
        if rows: print(f"{group}: {len(rows)} artists, {sum(r[2] for r in rows)} songs")
    for r in report: print(f"  {r[0]:17s} {r[1]:22s} {r[2]:5d}  {r[3]}")
    print(f"\ndata/korea_extra.csv: {len(final)} songs by {final.artists.nunique()} artists")
    return report


if __name__ == "__main__":
    main()
