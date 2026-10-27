"""Mapping from country/language labels to Spotify `track_genre` values.

The dataset has no country column, so a genre is used as a proxy for place.
"""

COUNTRY_GENRES = {
    "Japan": ["j-pop", "j-rock", "j-idol", "j-dance", "anime"],
    "South Korea": ["k-pop"],
    "China (Mandarin)": ["mandopop"],
    "Hong Kong (Cantonese)": ["cantopop"],
    "India": ["indian"],
    "Iran": ["iranian"],
    "Turkey": ["turkish"],
    "Malaysia": ["malay"],
    "Brazil": ["brazil", "mpb", "samba", "pagode", "sertanejo", "forro"],
    "France": ["french"],
    "Germany": ["german"],
    "Sweden": ["swedish"],
    "Spanish-language": ["spanish", "latino", "salsa", "tango", "reggaeton"],
}


def in_country(genres, country):
    """True if a song's genre set belongs to `country` and to no other country.

    Songs tagged with genres of two different countries are ambiguous (e.g. a
    Tamil song tagged both `indian` and `k-pop`), so they are excluded.
    """
    own = COUNTRY_GENRES[country]
    others = {g for c, gs in COUNTRY_GENRES.items() if c != country for g in gs}
    return not genres.isdisjoint(own) and genres.isdisjoint(others)


# Pseudo-country for "search every country pool at once" (shown as 전체 in the app).
ALL_COUNTRIES = "All"

# "English-speaking" is handled separately from COUNTRY_GENRES on purpose: its genres
# (pop, rock, dance...) are generic and also appear on songs from other countries, so
# they must not be used to exclude songs from those countries in in_country().
ENGLISH_COUNTRY = "English-language"
ENGLISH_GENRES = [
    "pop", "indie-pop", "power-pop", "synth-pop",
    "rock", "alt-rock", "alternative", "hard-rock", "grunge", "indie", "emo",
    "punk", "punk-rock", "metal", "heavy-metal",
    "hip-hop", "r-n-b", "soul", "dance", "british",
    "acoustic", "singer-songwriter", "songwriter", "folk",
    "country", "honky-tonk", "bluegrass", "blues",
]
# Generic-looking tags that still point to non-English music; songs with them are left out.
ENGLISH_EXCLUDED_TAGS = ["latin", "world-music", "dancehall", "reggae", "children"]


def all_country_genres():
    """Every genre that belongs to one of the (non-English) countries."""
    return {g for genres in COUNTRY_GENRES.values() for g in genres}
