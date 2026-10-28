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

## 11. ReccoBeats recommendations (tested, not used)

To see whether a "전체" option could find songs beyond the dataset, we tested
ReccoBeats' recommendation endpoint (`/v1/track/recommendation`) with two seeds,
without changing the app:

- It works with a Spotify ID as the seed (dataset songs). An ISRC cannot be a
  seed directly (HTTP 400); it first has to be turned into ReccoBeats' own ID
  with `/audio-features?ids=<ISRC>` (Deezer songs, +0.4 s).
- Up to 100 songs per call (`size` max 100), about 85-92 actually returned, and
  a different random set each time (two calls overlap by only ~25%).
- Their 9 audio features come from `/audio-features`, at most 40 ids per request
  (3 requests for 90 songs). None were missing. A search takes about 2-3 s.
  No API key; about 35 calls hit no rate limit (none is published).
- Target values (energy, valence...) were accepted but had no effect on quality.

Quality, using our weighted distance on the scaled features (lower = closer):

| Seed | ReccoBeats recommendations (median) | Random dataset songs (median) | Closest recommendation | Our dataset's best 10 (median) |
|---|---|---|---|---|
| Someone Like You (Adele) | 4.80 | 4.96 | 1.57 | **0.59** |
| Smells Like Teen Spirit (Nirvana) | 3.13 | 4.03 | 1.32 | **0.51** |

The recommendations are barely closer in mood than random songs (Adele) or
somewhat closer (Nirvana), and even the best of about 90 is 2-3 times farther
than our worst top-10 match. They have no genre or country, and 12-14 of the
~90 are already in the dataset. **Decision: not used.**

## 12. "전체" (all countries)

"전체" is the first item of the country dropdown and searches all 14 pools
(13 countries + 영어권) combined: 31,409 songs. The pools do not overlap, so
every song belongs to exactly one country. The same exclusions and the same
matching (weighted Euclidean + style 0.2) apply, because the combined pool is
simply the union of the finished pools (`Recommender._pool("All")`).
The results table has no country column (one was tried and removed). 전체 is also
the default selection of the dropdown. The album-cover column of the table is
headed "앨범".

## 13. Many more Korean songs (MusicBrainz + Deezer + ReccoBeats)

The dataset has only about 400 Korean songs, almost all K-pop (section 4). To get a wider mix
(indie, hip-hop, rock bands, ballad, R&B, folk, lesser-known artists), `scripts/collect_korea_extra.py`
collects songs from three free services without any key and writes **`data/korea_extra.csv`**:

1. **MusicBrainz**: every artist registered in South Korea with the tags indie, hip hop, rock, ballad,
   r&b or folk (470 artists; 1 request per second, User-Agent with the project URL).
2. **Deezer**: the artist by exact name -> up to 5 albums -> tracks with ISRC. Also the artists of
   Deezer playlists ("korean indie", "한국 인디", "korean hip hop", ...); a playlist artist is kept
   only if MusicBrainz confirms South Korea or the name has Hangul. Related artists were not used
   (they drift towards K-pop and foreign artists).
3. **ReccoBeats**: the 9 audio features and the Spotify id (the app needs it for the player and
   covers) for each ISRC.

Songs already in the dataset (125), instrumental versions, songs with no features or tempo 0 and
duplicates are skipped. The `genres` column is built from the MusicBrainz tags (or the playlist
query) with the dataset's genre names: rock, ballad, hip-hop, r-n-b, folk, indie, ... so the style
bonus works for Korea. `STYLE_FAMILIES` got the tag `ballad` and a new style `indie`.
`review/korea_extra_artists.csv` lists every artist (song count, genres, MusicBrainz country,
example title, how the artist was verified, share of Korean ISRCs) to check by hand;
`review/korea_extra_rejected_artists.csv` lists the artists that were left out and why.

Result: **14,555 songs by 640 artists** (MusicBrainz 322 artists / 8,005 songs, playlists 318 /
6,550). Main style of the songs: indie 27%, hip-hop 23%, ballad 20%, rock 15%, R&B 9%, folk 6%.

How the app uses them (`Recommender`, parameter `extra_path`): the songs join the dataset and all
belong to **한국** (and so to 전체), never to 영어권. The scaler is still fitted on the original
dataset, so results for the other countries do not change. `excluded_tracks.csv` and
`removed_from_country.csv` still apply to them. Pool sizes: 한국 400 -> **14,955**, 전체 31,409 ->
**45,963**, 영어권 11,990 -> 11,989 (one song lost because its artist is now in the Korean pool).
Genre tags in the 한국 pool: hip-hop 28%, indie 27%, ballad 23%, rock 21%, r-n-b 19%, k-pop 17%,
pop 11%, folk 9%, singer-songwriter 6% (a song can have several).

Before / after, top 10 (Euclid + weights + style 0.2):

| Input -> 한국 | Before | After |
|---|---|---|
| Adele "Someone Like You" (british;soul) | SOYOU, LeeHi, TAEYEON, BIBI, Punch... (all K-pop) | NIve, Naul, Brown Eyes, Yerin Baek, LambC, Brown Eyed Soul... (Korean R&B/soul) |
| Nirvana "Smells Like Teen Spirit" (rock) | I-LAND, GFRIEND, TXT, BTS x5, Stray Kids | TAEMIN, Boohwal, Sister's Barbershop x2, Shin Hae Chul, SEOTAIJI, youjeen, Xdinary Heroes... (Korean rock) |

Both new lists have no song in common with the old ones: all 10 results are new songs.

**The namesake problem.** Deezer often has several artists with the same name, and the first
version of the collection took the one with the most fans: it put the American band KISS
("Beth"), the Danish group Kandis and "Elo" (ELO) into the Korean pool. The check now (see the
top of the script): an artist with Hangul in its name or a song title is accepted; every other
artist is compared with MusicBrainz's own links: its Deezer page must be the artist we used (if
MusicBrainz links another Deezer page we switch to it, 32 artists), or its Spotify artist must be
the one ReccoBeats reports for the songs. If they point elsewhere the artist is left out. If
MusicBrainz has no usable link, an artist is accepted when most of its ISRCs start with the
country code KR (songs from Korean labels), otherwise a unique name is kept and an ambiguous one
is left out. Outcome for the 865 artists checked: 397 Hangul, 200 Deezer link, 74 Spotify link,
46 Korean ISRCs, 49 unique name without any link, 32 switched = 798 accepted; **67 artists
(2,509 songs) left out** (47 ambiguous name without any evidence, 20 whose Spotify artist does not
match). 640 of the accepted artists have songs in the file (the others had no songs with features).

Limits: 26 artists in the file are kept only because their name is unique on Deezer and
MusicBrainz has no link (e.g. "Suu" has a Spanish song, so some of these are probably wrong); the Korean ISRC share
is only positive evidence (real indie artists with a foreign distributor have other codes, so
some real artists such as JAMBINAI are among the left-out ones); a wrong link in MusicBrainz
would pass the check. The genre tags come from MusicBrainz and are loose (K-pop groups tagged
`rock` or `hip-hop`). Only 27% of the songs have Hangul in the title or artist, because many
Korean artists use English names. **These songs were not reviewed by hand** (unlike the 400
dataset songs and the Japan and 영어권 reviews), only their artists can be checked in the review
file; the app's footer still says that Korea was reviewed by hand.

Rerun: `python scripts/collect_korea_extra.py` (options `--max-albums`, `--limit-artists`,
`--no-playlists`). Every network answer is cached in `scripts/.cache/korea_extra/` (not committed),
so a rerun takes seconds and an interrupted run continues. The first full run took about
1.5 hours (the ReccoBeats features for 21,000 ISRCs and the MusicBrainz checks are the slow
parts, because of the 1 request per second limit and some rate limiting). To remove an artist or a
song, add the track ids to `data/excluded_tracks.csv`.

## 14. Hand review of the extra Korean artists

`review/korea_artist_review.csv` holds the decisions made by hand for the extra songs of section 13
(artist, list, decision, reason). `scripts/apply_korea_review.py` applies them to
`data/korea_extra.csv` (run it after `collect_korea_extra.py`; it is safe to run twice):

- `remove` (12 artists, 294 songs): dropped. Foreign namesakes such as Suu, Babo, Girls 96, Rose.
- `check`, kept list (30 artists): kept only if most songs are clearly Korean (a KR ISRC, Hangul in the title or
  artist, or a featured artist with a Hangul name). **29 failed (502 songs), 1 passed** (Girls On Top, 5 songs).
  The failed ones are mostly English-titled indie acts released through foreign distributors (Dept, Nogymx,
  Lunar Isles, Black String, Nokdu...), so the rule cannot tell them from foreign namesakes.
- `rescue` and `check`, rejected list (60 artists): the Korean Deezer page is searched under the Hangul names
  (MusicBrainz aliases plus `review/korea_artist_korean_names.csv`) and the name; every exact-name page (up to 8)
  is looked at; the best one is used if most of its songs, and most of the songs that end up in the file, have a KR
  ISRC or a Hangul title. **15 rescued (205 songs)**: Aleph, Amin, B JYUN., Gemini, Tei, Vibe, Zayvo, 김기쁨 (Lunch),
  도리 (DORI), 빈센트블루, 지아, 최성원, 플레이백, 후이, 희주. **42 stay unverified** (nothing added): 13 with no page
  under those names, 23 with a page that is not Korean enough, 5 whose Korean page is real but has no new songs
  with features (Kim Seungmin, Park Hye Kyoung, Suzy, Jay B, Rohann), and Jerry K (page 69% Korean, but only 38% of
  its songs with features).
- `keep` (Yuta, LISA, YUQI: members of K-pop groups), `keep_out` (KISS, Kandis), `already_in`: nothing.
- **Explicit overrides** (`review/korea_artist_overrides.csv`, applied instead of the rule for the artists named):
  - **JAMBINAI**, mode `page`: all songs of the real band page (Deezer id 3720001). Its albums are on a UK label
    (Bella Union), so the ISRCs start with `GB` and the rule rejected it. **21 songs** added (30 candidates minus
    instrumental versions, duplicates and songs without features). The tiny 잠비나이 page is no longer used.
  - **Exhibition (전람회)**, mode `kr_isrc`: from its two English-named Deezer pages only the songs with a KR ISRC:
    **18 songs** (27 candidates).
  - **Toy (토이)**, mode `kr_isrc`: none of its 8 English-named pages has a song with a KR ISRC, so **nothing**
    was added (the 토이 page has no songs at all).

Numbers: the file went from 14,555 songs / 640 artists (section 13) to **14,003 songs by 615 artists**. 한국 is
400 + 14,003 = **14,403 songs** (706 artists counting featured artists, 673 first-listed), 전체 45,411, 영어권
11,989. Main style of the extra songs: indie 26%, hip-hop 22%, ballad 20%, rock 15%, R&B 10%, folk 6%.
Adele -> 한국: 9 of the 10 songs are the same as before the review, Vibe (a rescued R&B duo) enters at #7;
Nirvana -> 한국: unchanged (all 10 the same). The overrides did not change either list.

Things the rule cannot see: real artists with foreign distributors fail it (that is why JAMBINAI needed an
override; Dept, Nogymx, Lunar Isles and Black String were dropped by it). A rescued page with only 1-5 songs
(지아, 후이, 희주, 빈센트블루) is found by name only, so it is worth a glance in `review/korea_extra_artists.csv`
(the `identity_check` column says which page was used). `review/korea_extra_rejected_artists.csv` lists the
50 artists that are still left out. The song counts in the app are computed (the picker shows "N곡 검색됨");
no text in the app contains a fixed number of songs.
