"""Find songs from a chosen country that sound like a given song.

Works without Streamlit. Terminal usage:
    python recommender.py search "bohemian"
    python recommender.py recommend "bohemian" Japan [--pick 0] [-n 10]
"""
import argparse

import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler

from countries import COUNTRY_GENRES, in_country

DATA_PATH = "data/cleaned.csv"
FEATURES = [
    "valence", "energy", "danceability", "acousticness", "tempo",
    "loudness", "speechiness", "instrumentalness", "liveness",
]


class Recommender:
    def __init__(self, path=DATA_PATH):
        self.df = pd.read_csv(path)
        # Scale on the full dataset so any input song (any genre) lands in the
        # same feature space as the candidates.
        self.X = StandardScaler().fit_transform(self.df[FEATURES])
        genre_sets = self.df["genres"].str.split(";").apply(set)
        self._country_mask = {
            country: genre_sets.apply(lambda g: in_country(g, country)).to_numpy()
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
        idx = candidates.nonzero()[0]

        sims = cosine_similarity(self.X[i : i + 1], self.X[idx])[0]
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
