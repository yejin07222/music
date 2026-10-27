"""Find songs from a chosen country that sound like a given song.

Works without Streamlit. Terminal usage:
    python recommender.py search "bohemian"
    python recommender.py recommend "bohemian" Japan [--pick 0] [-n 10]
"""
import argparse
import os

import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler

from countries import COUNTRY_GENRES, in_country

DATA_PATH = "data/cleaned.csv"
EXCLUDED_PATH = "data/excluded_tracks.csv"  # hand-reviewed wrong-country songs
INCLUDED_PATH = "data/included_tracks.csv"  # hand-added songs (track_id, country)
FEATURES = [
    "valence", "energy", "danceability", "acousticness", "tempo",
    "loudness", "speechiness", "instrumentalness", "liveness",
]


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
        self.X = self.scaler.transform(self.df[FEATURES])
        genre_sets = self.df["genres"].str.split(";").apply(set)
        self._country_mask = {
            country: (
                genre_sets.apply(lambda g: in_country(g, country)).to_numpy()
                | self.df["track_id"].isin(included.get(country, ())).to_numpy()
            ) & not_excluded
            for country in COUNTRY_GENRES
        }

    @property
    def countries(self):
        return list(COUNTRY_GENRES)

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

    def recommend(self, track_id, country, n=10):
        """Top `n` songs from `country` most similar to the song `track_id`.

        Returns a DataFrame with a `similarity` column (cosine similarity of
        the scaled features, -1..1). The input song is never included.
        """
        if country not in self._country_mask:
            raise ValueError(f"Unknown country: {country!r}")
        matches = self.df.index[self.df["track_id"] == track_id]
        if len(matches) == 0:
            raise ValueError(f"Unknown track_id: {track_id!r}")
        i = matches[0]

        candidates = self._country_mask[country].copy()
        candidates[i] = False  # never recommend the input song itself
        return self._rank(self.X[i], candidates, n)

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

    def _rank(self, target, candidates, n):
        idx = candidates.nonzero()[0]
        sims = cosine_similarity(target.reshape(1, -1), self.X[idx])[0]
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
    r.add_argument("country", choices=list(COUNTRY_GENRES))
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
