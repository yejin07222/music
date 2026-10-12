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
