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

## 9. Hand review of Japan's j-rock songs

`review/japan_jrock_review.csv` lists the 889 Japan songs tagged `j-rock`, with
automatic hints (tier "LIKELY NOT JAPANESE" 188, "maybe" 316, no warning 385).
The hints are noisy: RADWIMPS and ONE OK ROCK were flagged only because some of
their songs are tagged `k-pop` in the dataset. So the decisions were made by
hand, **by artist** (first-listed artist; a Japanese main artist with a foreign
featured artist stays in Japan, e.g. ONE OK ROCK;5 Seconds of Summer):

- `E` = English-language: 43 artists, **88 songs**. Removed from Japan
  (`data/removed_from_country.csv`) and added to 영어권
  (`data/included_tracks.csv`).
- `N` = neither Japanese nor English (mostly Turkish, also Brazilian, Nordic and
  others): 36 artists, **94 songs**. Added to `data/excluded_tracks.csv`.
- Everything else (707 songs) is Japanese and stays. The marks are in the `keep`
  column (empty = Japanese). Excel turns names like `=LOVE` into `#NAME?`, so
  edit this file in a text editor or import it as text.

Numbers: Japan 3,883 -> **3,701** songs (-182). 영어권 13,330 -> **13,587** (+257:
the 88 E songs, plus 169 other songs by the same artists, which are no longer
blocked by the rule "no artist from another country's pool").

Nirvana -> Japan: the top 10 did not change. Dust in the Wind -> Japan: the
foreign songs (The Bangles, Big Star, Frank Zappa, Yeni Turku, Zeki Muren, MFO)
are gone and replaced by Japanese songs (Aimer, Motohiro Hata, Shogo Hamada,
KOBUKURO, RADWIMPS). 4 of the 10 songs are the same as before.

Not done: the other Japan genres (j-pop, j-idol, j-dance, anime) were not
reviewed, and only South Korea and Japan's j-rock have been checked by hand.

## 10. Hand review of all 영어권 artists and Japan's other genres

Two more artist lists were classified by hand and applied by the **first-listed
artist** of each song (featured artists do not decide):

- `review/english_pool_remove.csv`: 1,073 artists that are not English-language
  (Spanish, Punjabi, Hindi, Indonesian, Tamil, Portuguese...). Their songs were
  removed from 영어권 only: **2,826 songs** (`data/removed_from_country.csv`,
  country `English-language`). Other countries' pools were not touched.
- `review/japan_other_marks.csv` (Japan songs outside the j-rock review):
  - `E` English-language (456 artists, mostly Jamaican dancehall and Western
    jazz): **1,180 songs** removed from Japan and added to 영어권.
  - `N` neither Japanese nor English (77 artists): **133 songs** removed from
    Japan and added to `data/excluded_tracks.csv`.
  - Artists not in the file are Japanese and stay.
- `review/unsure_artists.txt` (30 artists): left as they are. One of them,
  Zack Tabudlo, was also in the removal list; his 16 songs stay in 영어권.
- Names that did not match a first artist (328 + 301) only appear as featured
  artists, so those songs stay (13 songs in each list). One song,
  "Invincible (feat. Stefflon Don)" by Sidhu Moose Wala, only joined the 영어권
  pool after the Japan removals freed its featured artist; a second pass
  removed it. If more reviews are applied, run the pass again until nothing is
  left. The same happened to one N-marked song ("Intuisi" by Yura Yunita,
  Indonesian), which was removed from 영어권 as well (the 2,827th song).

Counts: Japan 3,701 -> **2,388** (-1,313). 영어권 13,587 -> **11,990**
(-2,827 removed, +1,180 moved from Japan, +50 songs that joined because their
artists are no longer in Japan's pool). South Korea (400) and the other pools
are unchanged.

Before/after (default matching):
- Nirvana -> Japan: identical top 10 (all `j-rock`).
- BTS "21st Century Girl" -> 영어권: 5 of 10 songs are the same. The Punjabi
  song by Sidhu Moose Wala at #1 is gone; the new entries are mostly dancehall
  songs that moved over from Japan (Charly Black, Koffee, Tanto Metro,
  Vybz Kartel).

Not done: j-pop, j-idol, j-dance and anime artists were reviewed only through
the artist list above; the other countries' pools (India, Iran, Turkey,
Malaysia, China, Hong Kong...) were not reviewed. Files from Windows downloads
(`*:Zone.Identifier`) are ignored by git.
