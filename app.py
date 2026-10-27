"""Streamlit UI: find songs from a chosen country that sound like a song you like.

Run: streamlit run app.py
"""
import streamlit as st

from countries import COUNTRY_GENRES
from recommender import Recommender

N_RESULTS = 10
SHOWN_GENRES = 3


@st.cache_resource
def load_recommender():
    return Recommender()


def country_label(country):
    genres = COUNTRY_GENRES[country]
    more = ", ..." if len(genres) > SHOWN_GENRES else ""
    name = country.replace(" (", " - ").replace(")", "")  # avoid nested parentheses
    return f"{name} ({', '.join(genres[:SHOWN_GENRES])}{more})"


def song_label(row):
    return f"{row.track_name} - {row.artists.replace(';', ', ')}  [{row.genres.replace(';', ', ')}]"


st.set_page_config(page_title="Mood Match", page_icon="🎧")
st.title("🎧 Mood Match")
st.write("Pick a song you like and a country. We'll find songs from that country with a similar mood.")

rec = load_recommender()

query = st.text_input("Search for a song or artist", placeholder="e.g. Someone Like You")
country = st.selectbox("Find songs from", rec.countries, format_func=country_label)

if not query.strip():
    st.info("Type a song title or artist name to get started.")
    st.stop()

found = rec.search(query)
if found.empty:
    st.warning(f"No songs found for “{query}”. Try a different spelling or just part of the title.")
    st.stop()

songs = {row.track_id: row for row in found.itertuples()}
track_id = st.selectbox(
    f"Which song? ({len(found)} found, most popular first)",
    list(songs),
    format_func=lambda tid: song_label(songs[tid]),
)

st.subheader(f"Songs from {country} with a similar mood")
results = rec.recommend(track_id, country, N_RESULTS)
if results.empty:
    st.warning(f"No songs available for {country}.")
    st.stop()

table = results[["track_name", "artists", "genres"]].reset_index(drop=True)
table.index = table.index + 1
table.index.name = "Rank"
table.columns = ["Title", "Artist", "Genre"]
table["Artist"] = table["Artist"].str.replace(";", ", ")
table["Genre"] = table["Genre"].str.replace(";", ", ")
st.dataframe(table, width="stretch")
st.caption("Ranked from most to least similar. Country is approximated from Spotify genre tags, so a few songs may be off.")
