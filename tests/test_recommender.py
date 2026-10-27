import pandas as pd
import pytest

from countries import COUNTRY_GENRES, ENGLISH_COUNTRY, ENGLISH_EXCLUDED_TAGS, all_country_genres
from recommender import Recommender, has_non_latin


@pytest.fixture(scope="module")
def rec():
    return Recommender()


def test_has_non_latin():
    assert has_non_latin("밤편지") and has_non_latin("あの日") and has_non_latin("Song 신청곡")
    assert has_non_latin("Привет") and has_non_latin("हिंदी")
    assert not has_non_latin("Mon Grand-Père") and not has_non_latin("Corazón (Remix) #1 & 2")


def test_country_pools_exist_and_south_korea_is_reviewed(rec):
    assert set(rec.countries) == set(COUNTRY_GENRES) | {ENGLISH_COUNTRY}
    assert int(rec._country_mask["South Korea"].sum()) == 400


def test_english_pool_rules(rec):
    d = rec.df
    sel = d[rec._country_mask[ENGLISH_COUNTRY]]
    assert len(sel) > 10_000
    genres = sel["genres"].str.split(";").apply(set)
    banned = all_country_genres() | set(ENGLISH_EXCLUDED_TAGS)
    assert genres.apply(lambda g: g.isdisjoint(banned)).all()
    assert not sel["track_name"].apply(has_non_latin).any()
    assert not sel["artists"].apply(has_non_latin).any()
    excluded = set(pd.read_csv("data/excluded_tracks.csv")["track_id"])
    assert excluded.isdisjoint(sel["track_id"])


def test_english_pool_has_no_artist_from_another_country(rec):
    others = [m for c, m in rec._country_mask.items() if c != ENGLISH_COUNTRY]
    in_other = pd.Series(False, index=rec.df.index)
    for m in others:
        in_other |= m
    other_artists = {a for s in rec.df.loc[in_other, "artists"] for a in s.split(";")}
    sel = rec.df[rec._country_mask[ENGLISH_COUNTRY]]
    assert not sel["artists"].apply(lambda s: any(a in other_artists for a in s.split(";"))).any()


@pytest.mark.parametrize("country", [ENGLISH_COUNTRY, "Japan", "South Korea"])
@pytest.mark.parametrize("kwargs", [{}, {"method": "euclid", "weighted": True, "style": True}])
def test_input_song_is_never_recommended(rec, country, kwargs):
    d = rec.df
    adele = d[(d.track_name == "Someone Like You") & (d.artists == "Adele")].iloc[0].track_id
    assert adele in set(d.track_id[rec._country_mask[ENGLISH_COUNTRY]])  # she is in the pool
    pool = list(d.track_id[rec._country_mask[country]][:50]) + [adele]
    for tid in pool:
        out = rec.recommend(tid, country, 10, **kwargs)
        assert tid not in set(out.track_id) and len(out) == 10


def test_default_method_is_still_cosine(rec):
    d = rec.df
    tid = d[(d.track_name == "Someone Like You") & (d.artists == "Adele")].iloc[0].track_id
    out = rec.recommend(tid, "South Korea", 3)
    assert out.track_name.tolist() == ["ONLY", "I Miss You", "그대라는 시"]


def test_unknown_inputs_raise(rec):
    with pytest.raises(ValueError):
        rec.recommend("nope", "Japan")
    with pytest.raises(ValueError):
        rec.recommend(rec.df.track_id.iloc[0], "Narnia")
    with pytest.raises(ValueError):
        rec.recommend(rec.df.track_id.iloc[0], "Japan", method="manhattan")
