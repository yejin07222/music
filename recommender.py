"""Find songs from a chosen country that sound like a given song.

Works without Streamlit. Terminal usage:
    python recommender.py search "bohemian"
    python recommender.py recommend "bohemian" Japan [--pick 0] [-n 10]
"""
import argparse
import functools
import os
import unicodedata

import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler

from countries import COUNTRY_GENRES, ENGLISH_COUNTRY, ENGLISH_EXCLUDED_TAGS, ENGLISH_GENRES, all_country_genres, in_country

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")  # works from any cwd
DATA_PATH = os.path.join(_DATA_DIR, "cleaned.csv")
EXCLUDED_PATH = os.path.join(_DATA_DIR, "excluded_tracks.csv")  # hand-reviewed wrong-country songs
INCLUDED_PATH = os.path.join(_DATA_DIR, "included_tracks.csv")  # hand-added songs (track_id, country)
FEATURES = [
    "valence", "energy", "danceability", "acousticness", "tempo",
    "loudness", "speechiness", "instrumentalness", "liveness",
]

# Per-feature multipliers on the scaled features (used by the "weighted" methods):
# the mood-defining features count more, liveness and speechiness less.
FEATURE_WEIGHTS = {
    "valence": 1.5, "energy": 1.5, "acousticness": 1.5, "danceability": 1.5, "tempo": 1.5,
    "loudness": 1.0, "instrumentalness": 1.0, "liveness": 0.5, "speechiness": 0.5,
}

# Broad styles -> dataset genre tags. A song has a style if any of its tags is listed.
STYLE_FAMILIES = {
    "rock": {"rock", "alt-rock", "hard-rock", "punk-rock", "punk", "grunge", "psych-rock", "rock-n-roll",
             "j-rock", "emo", "goth", "metal", "heavy-metal", "metalcore", "hardcore", "rockabilly", "guitar"},
    "ballad": {"sad", "romance", "singer-songwriter", "songwriter", "piano"},
    "hip-hop": {"hip-hop", "trip-hop"},
    "dance": {"dance", "edm", "electro", "house", "deep-house", "progressive-house", "chicago-house", "club",
              "techno", "trance", "disco", "party", "j-dance", "electronic"},
    "acoustic": {"acoustic", "folk", "bluegrass", "singer-songwriter", "guitar"},
    "r&b": {"r-n-b", "soul", "funk", "groove"},
}
STYLE_BONUS = 0.1  # added to the 0-1 similarity of candidates whose style matches the input's


@functools.lru_cache(maxsize=None)
def _non_latin_letter(ch):
    return ch.isalpha() and "LATIN" not in unicodedata.name(ch, "")


def has_non_latin(text):
    """True if `text` contains a letter outside the Latin script (Hangul, kana,
    Han, Indic scripts, Cyrillic, Arabic...). Accented Latin letters are fine."""
    return any(_non_latin_letter(ch) for ch in text)


class Recommender:
    def __init__(self, path=DATA_PATH, excluded_path=EXCLUDED_PATH, included_path=INCLUDED_PATH):
        self.df = pd.read_csv(path)
        excluded = set()
        if os.path.exists(excluded_path):
            excluded = set(pd.read_csv(excluded_path)["track_id"])
        not_excluded = ~self.df["track_id"].isin(excluded).to_numpy()
        included = {}  # country -> track_ids added by hand (no matching genre tag)
        if os.path.exists(included_path):
            for row in pd.read_csv(included_path).itertuples():
                included.setdefault(row.country, set()).add(row.track_id)
        # Scale on the full dataset so any input song (any genre) lands in the
        # same feature space as the candidates.
        self.scaler = StandardScaler().fit(self.df[FEATURES])
        self._weights = pd.Series(FEATURE_WEIGHTS)[FEATURES].to_numpy()
        self.X = self.scaler.transform(self.df[FEATURES])
        genre_sets = self.df["genres"].str.split(";").apply(set)
        self._styles = genre_sets.apply(
            lambda g: frozenset(name for name, tags in STYLE_FAMILIES.items() if not g.isdisjoint(tags))
        ).to_numpy()
        self._country_mask = {
            country: (
                genre_sets.apply(lambda g: in_country(g, country)).to_numpy()
                | self.df["track_id"].isin(included.get(country, ())).to_numpy()
            ) & not_excluded
            for country in COUNTRY_GENRES
        }
        # English-language (not reviewed by hand): an English-ish genre, no other country's
        # genre and none of ENGLISH_EXCLUDED_TAGS, only Latin letters in the title and artist,
        # and no artist who also appears in another country's pool.
        english, others = set(ENGLISH_GENRES), all_country_genres() | set(ENGLISH_EXCLUDED_TAGS)
        latin_only = ~(self.df["track_name"].apply(has_non_latin) | self.df["artists"].apply(has_non_latin))
        in_other_pool = np.any([m for m in self._country_mask.values()], axis=0)
        other_artists = {a for s in self.df.loc[in_other_pool, "artists"] for a in s.split(";")}
        foreign_artist = self.df["artists"].apply(lambda s: any(a in other_artists for a in s.split(";")))
        self._country_mask[ENGLISH_COUNTRY] = (
            genre_sets.apply(lambda g: not g.isdisjoint(english) and g.isdisjoint(others)).to_numpy()
            & latin_only.to_numpy()
            & ~foreign_artist.to_numpy()
            & not_excluded
        )

    @property
    def countries(self):
        return list(self._country_mask)

    def search(self, query, limit=20):
        """Songs whose title or artist contains `query` (case-insensitive),
        most popular first."""
        query = query.strip()
        if not query:
            return self.df.iloc[0:0]
        hit = (
            self.df["track_name"].str.contains(query, case=False, regex=False)
            | self.df["artists"].str.contains(query, case=False, regex=False)
        )
        return self.df[hit].sort_values("popularity", ascending=False).head(limit)

    def recommend(self, track_id, country, n=10, method="cosine", weighted=False, style=False):
        """Top `n` songs from `country` most similar to the song `track_id`.

        Returns a DataFrame with a `similarity` column and the input song is
        never included. With the defaults (the original method) `similarity`
        is the cosine similarity of the scaled features, -1..1.

        method:   "cosine" (original) or "euclid" (similarity = 1 / (1 + distance)).
        weighted: scale features by FEATURE_WEIGHTS first.
        style:    add STYLE_BONUS to candidates sharing a style (rock, dance, ...)
                  with the input song; `similarity` then includes the bonus.
        """
        if country not in self._country_mask:
            raise ValueError(f"Unknown country: {country!r}")
        matches = self.df.index[self.df["track_id"] == track_id]
        if len(matches) == 0:
            raise ValueError(f"Unknown track_id: {track_id!r}")
        i = matches[0]

        candidates = self._country_mask[country].copy()
        candidates[i] = False  # never recommend the input song itself
        return self._rank(self.X[i], candidates, n, method, weighted, self._styles[i] if style else None)

    def recommend_from_mood(self, mood, country, n=10):
        """Like `recommend`, but the target is a mood instead of a song.

        `mood` maps some of FEATURES to raw values (e.g. {"valence": 0.8,
        "tempo": 140}). Features not given are set to the dataset average, so
        they do not pull the ranking either way.
        """
        if country not in self._country_mask:
            raise ValueError(f"Unknown country: {country!r}")
        unknown = set(mood) - set(FEATURES)
        if unknown:
            raise ValueError(f"Unknown features: {sorted(unknown)}")
        raw = pd.DataFrame([{**dict(zip(FEATURES, self.scaler.mean_)), **mood}])
        target = self.scaler.transform(raw[FEATURES])[0]
        return self._rank(target, self._country_mask[country], n)

    def _rank(self, target, candidates, n, method="cosine", weighted=False, styles=None):
        if method not in ("cosine", "euclid"):
            raise ValueError(f"Unknown method: {method!r}")
        idx = candidates.nonzero()[0]
        X, t = self.X[idx], target
        if weighted:
            X, t = X * self._weights, t * self._weights
        if method == "cosine":
            sims = cosine_similarity(t.reshape(1, -1), X)[0]
        else:
            sims = 1.0 / (1.0 + np.linalg.norm(X - t, axis=1))
        if styles:
            sims = sims + STYLE_BONUS * np.array([bool(styles & c) for c in self._styles[idx]])
        top = sims.argsort()[::-1][:n]
        result = self.df.iloc[idx[top]].copy()
        result["similarity"] = sims[top]
        return result


def _show(df, cols):
    print(df[cols].to_string(index=True, float_format=lambda x: f"{x:.3f}"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="search songs by title or artist")
    s.add_argument("query")
    r = sub.add_parser("recommend", help="recommend songs from a country")
    r.add_argument("query")
    r.add_argument("country", choices=list(COUNTRY_GENRES) + [ENGLISH_COUNTRY])
    r.add_argument("--pick", type=int, default=0, help="row number from the search results (default 0)")
    r.add_argument("-n", type=int, default=10)
    args = p.parse_args()

    rec = Recommender()
    found = rec.search(args.query)
    if found.empty:
        raise SystemExit(f"No songs found for {args.query!r}")
    cols = ["track_name", "artists", "genres", "popularity"]

    if args.cmd == "search":
        _show(found.reset_index(drop=True), cols)
        return

    found = found.reset_index(drop=True)
    song = found.iloc[args.pick]
    print(f"Input: {song['track_name']} - {song['artists']} [{song['genres']}]")
    print(f"Country: {args.country}\n")
    out = rec.recommend(song["track_id"], args.country, args.n).reset_index(drop=True)
    _show(out, ["track_name", "artists", "genres", "similarity"])


if __name__ == "__main__":
    main()
