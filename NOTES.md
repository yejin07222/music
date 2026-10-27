# Notes: mislabeled genres

The dataset has no country column, so a country is approximated by a set of
Spotify `track_genre` values (see `countries.py`). Some of those genre tags
are wrong, e.g. Tamil and Kannada film songs tagged `k-pop`. This is what we
found and what we did about it.

## 1. Multi-country rule (partly worked)

Rule: a song counts for a country only if it has one of that country's genres
**and none** of another country's genres (`countries.in_country()`).

- It removed songs tagged with two countries (e.g. `folk;indian;k-pop`).
  Pools shrank mostly for China (967 -> 843) and Hong Kong (955 -> 838).
- It did **not** fix the main problem: most wrong songs carry only the
  `k-pop` tag (or `k-pop;pop;pop-film`), so the rule cannot see them.
  Adele -> South Korea still returned Kannada and Tamil songs.

## 2. Manual review of South Korea

- Exported all 868 South Korea songs to `review/korea_review.csv` with
  automatic "suspicious" flags (artist also in another country's genre,
  `pop-film`, Indian-script text). 320 were flagged.
- Reviewed by hand: **473 removed (N), 395 kept**. Most removed songs had not
  been flagged, so the flags only helped as hints.
- The removed IDs are in `data/excluded_tracks.csv`; the recommender skips
  them. Non-Korean rap songs (e.g. Jack Harlow) were also tagged `k-pop`.

## 3. Adele ("Someone Like You") -> South Korea

| | Before review | After review |
|---|---|---|
| Top result | Naa Ninage Kaavalugaara (Kannada), 0.986 | ONLY, LeeHi |
| Wrong-country songs in top 10 | 4 (Kannada, 2x Tamil, Hindi) | 0 |
| Results | mix of K-pop and Indian film songs | Korean ballads (LeeHi, SOYOU, TAEYEON, BIBI, HEIZE, DAVICHI...) |

## 4. Looking for more Korean songs in other genres

After the review only 395 South Korea songs were left, so we searched songs
**not** tagged `k-pop` for Korean ones: Hangul in the title or artist name, or
an artist who appears in the 395 kept songs (`review/korea_candidates.csv`).

- 227 candidates were found. Only 6 had Hangul; the other 221 matched by
  artist and were mostly Western artists who featured on K-pop songs
  (Sia, Halsey, Nicki Minaj, ...), so they were ignored.
- Claude flagged the 6 Hangul songs as likely Korean. After a manual check,
  only **5 were really Korean** (the One Punch Man theme was not).
- The 5 are in `data/included_tracks.csv` and are added to South Korea by
  track ID, because their genres (singer-songwriter, opera, new-age) are not
  country genres.
- Result: South Korea has **400** songs. So the dataset contains only about
  400 Korean songs in total.

## 5. Remaining limitation

Only South Korea was reviewed. Other countries were **not** checked, and
similar mislabeling may exist (India, Turkey, Malaysia, China and Hong Kong
are the most likely). Genre is only a proxy for place or language, so
results can still contain songs from other countries.

Song search is a plain case-insensitive substring match on title or artist,
so remasters, live versions and medleys appear as separate entries.

## 6. Songs that are not in the dataset

If a search finds nothing in the dataset, the app looks the song up online:
title -> **Deezer** search (gives the ISRC) -> **ReccoBeats** audio features
by ISRC (`online_lookup.py`). The features use the same scale as the dataset,
so the same ranking is used. Any error falls back to the mood sliders.

Why these two services:
- Spotify's Search API now needs a Premium account (since February 2026), and
  Spotify closed its own audio-features endpoint to new apps.
- Deezer search and ReccoBeats need no API key and are free. Deezer returns an
  ISRC for each result; ReccoBeats accepts an ISRC as its `ids` value.
- Both are unofficial third-party services without any guarantee, so the
  dataset search never depends on them.

Known limits: Deezer's top results are sometimes covers or other versions
(e.g. searching a Korean title alone returns mostly piano covers), and
ReccoBeats does not have every song. Features for another release of the same
recording can differ slightly from the dataset's values.

## 7. English-language (영어권)

Added as an extra option. It is **not reviewed by hand** and may include some
non-English songs.

- Genres: pop, indie-pop, power-pop, synth-pop, rock, alt-rock, alternative,
  hard-rock, grunge, indie, emo, punk, punk-rock, metal, heavy-metal, hip-hop,
  r-n-b, soul, dance, british, acoustic, singer-songwriter, songwriter, folk,
  country, honky-tonk, bluegrass, blues (`ENGLISH_GENRES` in `countries.py`).
- Excluded: songs also tagged with any other country's genre, songs in
  `data/excluded_tracks.csv`, and songs with non-Latin letters (Hangul, kana,
  Han, Indic scripts, Cyrillic, Arabic...) in the title or artist.
- Cleanup (second round), because many non-English songs got through:
  1. songs by an artist who also appears in another country's pool are removed;
  2. songs tagged `latin`, `world-music`, `dancehall`, `reggae` or `children`
     are removed (`ENGLISH_EXCLUDED_TAGS`).
- The English genres are not used to exclude songs from the other countries
  (they are too generic), so those pools are unchanged.

Before / after the cleanup:

| | Before | After |
|---|---|---|
| Pool size | 15,818 songs | 13,330 songs (-2,488) |
| Not English in 2 random samples of 20 each (40 songs) | 12 of 40 (30%) | 13 of 40 (32.5%) |
| BTS "21st Century Girl" -> top 5 | 2 Hindi, 1 Portuguese, 1 Spanish, 1 English | 1 Spanish (Catupecu Machu), 4 English |

The sample counts were judged by Claude from the title and artist, not by a
language detector, and 1-2 songs per sample were uncertain. Samples of 40 are
small: the cleanup removed 16% of the pool but the share of non-English songs in
it did not drop measurably.

- Known problem: the genre tags say nothing about the language. Songs in Latin
  script from other languages still get through, mostly Spanish and Portuguese
  rock/metal bands, French and German artists, and Punjabi/Hindi hip-hop, when
  they are tagged only with generic genres and their artist is in no other pool.

## 8. Matching method

The app uses **Euclidean distance on weighted features, plus a style bonus of
0.2** (`MATCH` in `app.py`, `STYLE_BONUS` in `recommender.py`). The original
cosine method is still the default of `Recommender.recommend()`, so the
versions can be compared.

- Distance: similarity = 1 / (1 + Euclidean distance) on the scaled features.
- Weights (multipliers on the scaled features): valence, energy, acousticness,
  danceability, tempo 1.5; loudness, instrumentalness 1.0; liveness,
  speechiness 0.5 (`FEATURE_WEIGHTS`).
- Style: if the input song's genres include a style (rock, ballad, hip-hop,
  dance, acoustic, r&b; `STYLE_FAMILIES`), songs of the target country with a
  genre of the same style get +0.2. It only helps where the target pool has
  style tags: Japan yes, South Korea no (395 of 400 songs are only `k-pop`).
  Songs found online have no genre, so they use distance + weights only.

Nirvana "Smells Like Teen Spirit" -> Japan, rank of two songs we looked at:

| Method | Hyperventilation (RADWIMPS) | TATTOO (Akina Nakamori, j-idol) |
|---|---|---|
| A: cosine (original) | #2 | #5 |
| Euclid + weights | #13 | #10 |
| + style 0.1 | #10 | #44 |
| + style 0.2 | #9 | outside top 50 |
| + style 0.3 | #9 | outside top 50 |

With style 0.2 or 0.3 the top 10 is the same, all `j-rock`. The big drop of
Hyperventilation comes from the Euclidean/weighted distance, not from the style.

Overlap test, style 0.3 (same top 10 for 0.2): Nirvana "Smells Like Teen
Spirit" and Kansas "Dust in the Wind" (slow, soft rock) -> Japan share **0
songs** in their top 10 (also 0 with the original method), so the results do
depend on the input song.

Problem found by that test: 4 of the 10 results for the soft song were not
Japanese (The Bangles, Big Star, Frank Zappa, and Turkish songs by Yeni Turku,
Zeki Muren and MFO). Their only country tag is `j-rock`, and the style bonus
favours that tag. Japan's `j-rock` songs have not been reviewed by hand yet.
