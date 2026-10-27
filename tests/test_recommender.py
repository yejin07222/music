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


def _hand_added_english():
    inc = pd.read_csv("data/included_tracks.csv")
    return set(inc.loc[inc["country"] == ENGLISH_COUNTRY, "track_id"])


def test_english_pool_rules(rec):
    d = rec.df
    # songs added to 영어권 by hand (reviewed as English despite a j-rock tag) skip the genre rules
    sel = d[rec._country_mask[ENGLISH_COUNTRY] & ~d["track_id"].isin(_hand_added_english())]
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
    sel = rec.df[rec._country_mask[ENGLISH_COUNTRY] & ~rec.df["track_id"].isin(_hand_added_english())]
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


def test_style_bonus_default_and_mood_options(rec):
    import recommender

    assert recommender.STYLE_BONUS == 0.2
    mood = {"valence": 0.8, "energy": 0.8, "tempo": 130}
    a = rec.recommend_from_mood(mood, "Japan", 10)
    b = rec.recommend_from_mood(mood, "Japan", 10, method="euclid", weighted=True)
    assert len(a) == len(b) == 10 and a.track_id.tolist() != b.track_id.tolist()
    with pytest.raises(ValueError):
        rec.recommend_from_mood(mood, "Japan", method="manhattan")


def test_japan_review_is_applied(rec):
    d = rec.df
    japan, english = rec._country_mask["Japan"], rec._country_mask[ENGLISH_COUNTRY]
    review = pd.read_csv("review/japan_jrock_review.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    marks = review["keep"].str.strip().str.upper()
    e_ids, n_ids = set(review.track_id[marks == "E"]), set(review.track_id[marks == "N"])
    assert len(e_ids) == 88 and len(n_ids) == 94
    assert not d.track_id[japan].isin(e_ids | n_ids).any()  # both removed from Japan
    assert set(d.track_id[english]) >= e_ids  # E songs are in 영어권
    assert not d.track_id[english].isin(n_ids).any()  # N songs are in no pool
    kept = review.track_id[marks == ""]
    assert len(kept) == 707 and d.track_id[japan].isin(kept).sum() == 707  # all unmarked songs stay in Japan
    assert review.loc[review.artists == "ONE OK ROCK;5 Seconds of Summer", "keep"].eq("").all()


def _first_artist_keys(names):
    import unicodedata

    return {unicodedata.normalize("NFC", n).strip().casefold() for n in names}


def _first(rec):
    import unicodedata

    return rec.df["artists"].str.split(";").str[0].map(lambda x: unicodedata.normalize("NFC", x).strip().casefold())


def test_artist_marks_are_applied(rec):
    d, first = rec.df, _first(rec)
    japan, english = rec._country_mask["Japan"], rec._country_mask[ENGLISH_COUNTRY]
    unsure = _first_artist_keys(l.split("|")[0] for l in open("review/unsure_artists.txt", encoding="utf-8-sig") if l.strip())

    remove = pd.read_csv("review/english_pool_remove.csv", dtype=str, keep_default_na=False)
    marks = pd.read_csv("review/japan_other_marks.csv", dtype=str, keep_default_na=False)
    gone = _first_artist_keys(remove.artist) - unsure
    e_artists = _first_artist_keys(marks[marks.mark == "E"].artist) - unsure
    n_artists = _first_artist_keys(marks[marks.mark == "N"].artist) - unsure

    assert not (english & first.isin(gone)).any()  # non-English artists are out of 영어권
    assert not (japan & first.isin(e_artists | n_artists)).any()  # E and N artists are out of Japan
    assert (english & first.isin(e_artists)).sum() > 1000  # E songs moved to 영어권
    assert not first[english].isin(n_artists).any()  # N songs are in no 영어권
    # the removal from 영어권 does not touch the other countries' pools
    other = [m for c, m in rec._country_mask.items() if c not in ("Japan", ENGLISH_COUNTRY)]
    assert sum(int(m.sum()) for m in other) == 400 + 843 + 838 + 951 + 951 + 917 + 963 + 5031 + 958 + 786 + 840 + 3553
    # unsure artists are left as they were
    assert (english & (first == "zack tabudlo")).sum() == 16


def test_pool_sizes_after_reviews(rec):
    assert int(rec._country_mask["Japan"].sum()) == 2388
    assert int(rec._country_mask[ENGLISH_COUNTRY].sum()) == 11990
