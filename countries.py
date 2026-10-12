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
