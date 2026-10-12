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
