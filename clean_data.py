"""Clean data/dataset.csv and write a small data/cleaned.csv for the app.

Run: python clean_data.py
"""
import os

import pandas as pd

from countries import COUNTRY_GENRES, in_country

RAW_PATH = "data/dataset.csv"
CLEAN_PATH = "data/cleaned.csv"

FEATURES = [
    "valence", "energy", "danceability", "acousticness", "tempo",
    "loudness", "speechiness", "instrumentalness", "liveness",
]
KEEP = ["track_id", "track_name", "artists", "popularity"] + FEATURES + ["genres"]


def report(step, df):
    print(f"{step:<45}{len(df):>9,}")


def merge_genres(df, group_col):
    """Collapse rows sharing `group_col`: keep the most popular row and
    store the union of all their genres in a `genres` column (';'-joined)."""
    genres = df.groupby(group_col)["track_genre"].agg(
        lambda s: ";".join(sorted({g for x in s for g in x.split(";")}))
    )
    best = df.sort_values("popularity", ascending=False).drop_duplicates(group_col)
    best = best.drop(columns="track_genre").set_index(group_col)
    return best.join(genres.rename("genres")).reset_index()


def main():
    df = pd.read_csv(RAW_PATH, index_col=0)
    report("Loaded", df)

    df = df.dropna(subset=["track_name", "artists"])
    df = df[df["track_name"].str.strip().ne("") & df["artists"].str.strip().ne("")]
    report("Dropped rows with missing name/artist", df)

    df = df[df["tempo"] > 0]
    report("Dropped rows with tempo 0", df)

    df = merge_genres(df, "track_id")
    report("Merged duplicate track_id (genres kept)", df)

    # Same title + artist under different IDs (re-releases, compilations).
    df["_key"] = df["track_name"].str.lower().str.strip() + "|" + df["artists"].str.lower().str.strip()
    df["track_genre"] = df["genres"]
    df = df.drop(columns="genres")
    df = merge_genres(df, "_key")
    df = df.drop(columns="_key")
    report("Merged same title+artist (different IDs)", df)

    df[FEATURES] = df[FEATURES].round(3)  # smaller file; plenty of precision
    df = df[KEEP].sort_values("track_id").reset_index(drop=True)
    report("Final (columns trimmed)", df)

    df.to_csv(CLEAN_PATH, index=False)

    genre_sets = df["genres"].str.split(";").apply(set)
    print("\nSongs per country (songs tagged with another country's genre excluded):")
    for country in COUNTRY_GENRES:
        n = genre_sets.apply(lambda g: in_country(g, country)).sum()
        print(f"  {country:<24}{n:>7,}")

    print(f"\n{CLEAN_PATH}: {os.path.getsize(CLEAN_PATH) / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    main()
