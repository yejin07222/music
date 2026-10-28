import csv

import numpy as np
import pandas as pd
import pytest

import recommender
from recommender import FEATURES, Recommender, STYLE_FAMILIES

EXTRA_COLUMNS = ["track_id", "isrc", "track_name", "artists", "popularity"] + FEATURES + ["genres", "source"]


def extra_row(track_id, title, artist, genres, **features):
    base = {f: 0.5 for f in FEATURES} | {"tempo": 120.0, "loudness": -8.0} | features
    return {"track_id": track_id, "isrc": "KR" + track_id[:10].upper(), "track_name": title, "artists": artist,
            "popularity": 40, **base, "genres": genres, "source": "musicbrainz:indie"}


def write_extra(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EXTRA_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return str(path)


@pytest.fixture(scope="module")
def base():
    return Recommender(extra_path=None)


@pytest.fixture(scope="module")
def extra_file(tmp_path_factory):
    rows = [
        extra_row("A" * 22, "Indie Morning", "Mock Band", "indie;rock", valence=0.7, energy=0.9),
        extra_row("B" * 22, "Rap Night", "Mock Rapper", "hip-hop", valence=0.3, energy=0.4),
        extra_row("C" * 22, "Soft Ballad", "Mock Singer", "ballad;folk", acousticness=0.9, energy=0.2),
    ]
    return write_extra(tmp_path_factory.mktemp("extra") / "korea_extra.csv", rows)


@pytest.fixture(scope="module")
def withx(extra_file):
    return Recommender(extra_path=extra_file)


def test_extra_songs_join_korea_and_all_but_not_english(base, withx):
    d = withx.df
    ids = {"A" * 22, "B" * 22, "C" * 22}
    assert withx.n_extra == 3 and len(d) == len(base.df) + 3
    korea, english = withx._country_mask["South Korea"], withx._country_mask["English-language"]
    assert ids <= set(d.track_id[korea]) and int(korea.sum()) == int(base._country_mask["South Korea"].sum()) + 3
    assert not ids & set(d.track_id[english])  # Korean songs tagged indie/rock/folk must not become "English"
    assert ids <= set(d.track_id[withx._pool("All")]) and int(withx._pool("All").sum()) == int(base._pool("All").sum()) + 3
    for country in withx.countries:  # no other country gets them
        if country != "South Korea":
            assert not ids & set(d.track_id[withx._country_mask[country]])
            assert int(withx._country_mask[country].sum()) == int(base._country_mask[country].sum())
    assert set(withx.search("Rap Night").track_id) == {"B" * 22}  # searchable like any song


def test_scaler_and_existing_results_do_not_change(base, withx):
    assert np.allclose(withx.scaler.mean_, base.scaler.mean_) and np.allclose(withx.scaler.scale_, base.scaler.scale_)
    n = len(base.df)
    assert np.allclose(withx.X[:n], base.X)  # the original songs keep their numbers
    adele = base.df[(base.df.track_name == "Someone Like You") & (base.df.artists == "Adele")].iloc[0].track_id
    out = base.recommend(adele, "Japan", 10, method="euclid", weighted=True, style=True)
    out2 = withx.recommend(adele, "Japan", 10, method="euclid", weighted=True, style=True)
    assert out.track_id.tolist() == out2.track_id.tolist()  # other countries are untouched


def test_extra_songs_can_be_recommended_and_the_style_bonus_works(base, withx):
    d = withx.df
    mock_rock = d[d.track_id == "A" * 22].index[0]
    # use the extra song's own features as the "input": it must come first for a mood made of its numbers
    mood = {f: float(d.loc[mock_rock, f]) for f in FEATURES}
    top = withx.recommend_from_mood(mood, "South Korea", 3, method="euclid", weighted=True)
    assert top.track_id.iloc[0] == "A" * 22
    # style bonus: a rock input song prefers the Korean song tagged rock over an identical one tagged otherwise
    nirvana = d[(d.track_name.str.startswith("Smells Like Teen Spirit")) & (d.artists.str.contains("Nirvana"))].iloc[0].track_id
    plain = withx.recommend(nirvana, "South Korea", 400, method="euclid", weighted=True, style=False)
    styled = withx.recommend(nirvana, "South Korea", 400, method="euclid", weighted=True, style=True)
    gain = styled.set_index("track_id").similarity - plain.set_index("track_id").similarity
    assert gain["A" * 22] == pytest.approx(recommender.STYLE_BONUS)  # indie;rock -> rock style matches
    assert gain["B" * 22] == pytest.approx(0.0) and gain["C" * 22] == pytest.approx(0.0)  # hip-hop, ballad: not rock


def test_genre_names_used_for_the_extra_songs_match_the_style_families():
    # the six styles the collection script writes, each with a family the style bonus recognizes
    for tag, family in {"rock": "rock", "hip-hop": "hip-hop", "r-n-b": "r&b", "folk": "acoustic",
                        "ballad": "ballad", "indie": "indie"}.items():
        assert tag in STYLE_FAMILIES[family], (tag, family)


def test_exclusion_and_removal_lists_still_apply_to_extra_songs(extra_file, tmp_path):
    excluded = tmp_path / "excluded.csv"
    pd.DataFrame({"track_id": ["A" * 22]}).to_csv(excluded, index=False)
    removed = tmp_path / "removed.csv"
    pd.DataFrame({"track_id": ["B" * 22], "country": ["South Korea"]}).to_csv(removed, index=False)
    r = Recommender(extra_path=extra_file, excluded_path=str(excluded), removed_path=str(removed))
    korea = set(r.df.track_id[r._country_mask["South Korea"]])
    assert "A" * 22 not in korea and "B" * 22 not in korea and "C" * 22 in korea
    assert "A" * 22 not in set(r.df.track_id[r._pool("All")]) and "B" * 22 not in set(r.df.track_id[r._pool("All")])


def test_extra_rows_with_a_dataset_id_or_a_repeated_id_are_ignored(base, tmp_path):
    existing = base.df.track_id.iloc[0]
    rows = [extra_row(existing, "Same Id", "X", "indie"), extra_row("D" * 22, "New", "Y", "indie"), extra_row("D" * 22, "New again", "Y", "indie")]
    r = Recommender(extra_path=write_extra(tmp_path / "e.csv", rows))
    assert r.n_extra == 1 and len(r.df) == len(base.df) + 1 and r.df.track_id.is_unique


def test_missing_or_disabled_extra_file_gives_the_plain_dataset(base, tmp_path):
    for path in (None, str(tmp_path / "does_not_exist.csv")):
        r = Recommender(extra_path=path)
        assert r.n_extra == 0 and len(r.df) == len(base.df)


def test_the_real_extra_file_if_it_exists():
    import os

    if not os.path.exists(recommender.EXTRA_PATH):
        pytest.skip("data/korea_extra.csv has not been collected yet")
    extra = pd.read_csv(recommender.EXTRA_PATH)
    dataset = pd.read_csv(recommender.DATA_PATH)
    assert list(extra.columns) == EXTRA_COLUMNS and len(extra) > 1000
    assert extra.track_id.is_unique and extra.isrc.is_unique and not extra.track_id.isin(dataset.track_id).any()
    assert extra.track_id.str.fullmatch(r"[A-Za-z0-9]{22}").all()  # Spotify ids: the player and the covers need them
    assert extra[FEATURES].notna().all().all() and extra.genres.str.len().gt(0).all()
    for col in ("valence", "energy", "danceability", "acousticness", "speechiness", "instrumentalness", "liveness"):
        assert extra[col].between(0, 1).all(), col
    assert extra.tempo.gt(0).all() and extra.loudness.lt(10).all() and extra.popularity.between(0, 100).all()
    allowed = {"rock", "alt-rock", "emo", "indie", "indie-pop", "punk", "punk-rock", "metal", "heavy-metal", "hip-hop", "r-n-b",
               "soul", "funk", "ballad", "folk", "singer-songwriter", "acoustic", "country", "pop", "k-pop", "dance",
               "electronic", "edm", "house", "jazz", "blues"}
    assert set(g for s in extra.genres for g in s.split(";")) <= allowed
    assert extra.source.str.match(r"^(musicbrainz|playlist|review-rescue|review-override):").all()
    r = Recommender()
    assert r.n_extra == len(extra)
    excluded = set(pd.read_csv(recommender.EXCLUDED_PATH).track_id)
    expected = 400 + int((~extra.track_id.isin(excluded)).sum())
    assert int(r._country_mask["South Korea"].sum()) == expected  # 400 reviewed songs + the extras that are not excluded
    english = r._country_mask["English-language"]
    assert not r.df.track_id[english].isin(extra.track_id).any()


def test_the_extra_file_follows_the_hand_review():
    import os

    review_path = os.path.join(os.path.dirname(recommender.EXTRA_PATH), "..", "review", "korea_artist_review.csv")
    if not os.path.exists(recommender.EXTRA_PATH) or not os.path.exists(review_path):
        pytest.skip("no extra file or no review file")
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("apply_korea_review", Path(review_path).resolve().parent.parent / "scripts" / "apply_korea_review.py")
    akr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(akr)
    cke = akr.cke
    extra = pd.read_csv(recommender.EXTRA_PATH)
    extra["key"] = extra.artists.map(cke.norm)
    d = akr.load_decisions(review_path)
    present = set(extra.key)
    removed = set(d[(d.list == "kept") & (d.decision == "remove")].key)
    assert not removed & present  # "remove": gone
    keep = set(d[(d.list == "kept") & (d.decision == "keep")].key)
    assert keep <= present  # "keep": still there (K-pop group members)
    for key in set(d[(d.list == "kept") & (d.decision == "check")].key) & present:
        rows = extra[extra.key == key]  # a "check" artist that is still there must look Korean
        assert akr.korean_share(zip(rows.track_name, rows.artists, rows.isrc)) >= akr.EVIDENCE_MIN, key
    keep_out = set(d[(d.list == "rejected") & (d.decision == "keep_out")].key)
    assert not keep_out & present  # KISS and Kandis are still out
    rescued = extra[extra.source.str.startswith("review-rescue:")]
    assert rescued.artists.nunique() >= 10
    for _, rows in rescued.groupby("artists"):
        assert akr.korean_share(zip(rows.track_name, rows.artists, rows.isrc)) >= akr.EVIDENCE_MIN  # every rescued artist passed the rule
    assert extra.track_id.is_unique and not extra.duplicated(["track_name", "artists"]).any()


def test_the_extra_file_has_the_explicit_overrides():
    import os

    if not os.path.exists(recommender.EXTRA_PATH):
        pytest.skip("data/korea_extra.csv has not been collected yet")
    extra = pd.read_csv(recommender.EXTRA_PATH)
    name = extra.artists.str.lower()
    jambinai = extra[name == "jambinai"]  # the real band page: UK label, so GB ISRCs are expected
    assert len(jambinai) >= 15 and jambinai.isrc.str.startswith("GB").all() and jambinai.source.eq("review-override:page").all()
    exhibition = extra[name == "exhibition"]  # English-named pages: only the songs with a KR ISRC
    assert len(exhibition) >= 10 and exhibition.isrc.str.startswith("KR").all() and exhibition.source.eq("review-override:kr_isrc").all()
    assert not (name == "toy").any()  # none of Toy's English pages has a KR ISRC song
    assert not name.eq("잠비나이").any()  # the tiny Hangul page was replaced by the override
