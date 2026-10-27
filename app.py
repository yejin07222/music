"""Streamlit UI (Korean): find songs from a chosen country that sound like a song you like.

Run: streamlit run app.py
"""
import altair as alt
import pandas as pd
import streamlit as st

import media
import results_table
from recommender import Recommender
from online_lookup import LookupFailed, fetch_features, search_songs

N_RESULTS = 10
# Matching used by the app: Euclidean distance on weighted features, plus a style bonus when the
# input song's genres are known (see NOTES.md section 8).
MATCH = {"method": "euclid", "weighted": True}

# Display names only; the keys must match countries.COUNTRY_GENRES.
COUNTRY_LABELS = {
    "Japan": "일본",
    "South Korea": "한국",
    "China (Mandarin)": "중국",
    "Hong Kong (Cantonese)": "홍콩",
    "India": "인도",
    "Iran": "이란",
    "Turkey": "튀르키예",
    "Malaysia": "말레이시아",
    "Brazil": "브라질",
    "France": "프랑스어",
    "Germany": "독일",
    "Sweden": "스웨덴",
    "Spanish-language": "스페인어",
    "English-language": "영어권",
}

# Shown first in the country dropdown; the other countries follow in their usual order.
COUNTRY_ORDER_FIRST = ["South Korea", "Japan", "English-language", "China (Mandarin)"]

# Features shown in the "why this song" chart: (column, Korean name).
CHART_FEATURES = [
    ("valence", "밝기"),
    ("energy", "에너지"),
    ("danceability", "댄스성"),
    ("acousticness", "어쿠스틱"),
    ("tempo", "템포"),
    ("loudness", "음량"),
]
# Only these two are not already 0-1; they are rescaled for the chart.
RESCALED = ("tempo", "loudness")

SERIES_COLORS = ["#2a78d6", "#eb6834"]  # blue = my song, orange = the result


@st.cache_resource
def load_recommender():
    return Recommender()


LOOKUP_ERRORS = {
    "timeout": "응답이 너무 늦어서 곡 정보를 가져오지 못했어요.",
    "network": "곡 정보를 가져오는 중 연결에 문제가 있었어요.",
    "blocked": "서비스가 요청을 받아주지 않았어요 (접근 거부).",
    "rate_limit": "요청이 너무 많아 잠시 막혔어요. 조금 뒤에 다시 시도해 주세요.",
    "not_found": "이 곡의 분위기 정보를 찾을 수 없어요.",
    "no_results": "온라인에서도 이 곡을 찾지 못했어요.",
    "bad_response": "서비스에서 예상하지 못한 응답이 왔어요.",
}


def show_links(links):
    """Small 'listen on' links under a song; shown only if there are any."""
    text = media.links_markdown(links)
    if text:
        st.markdown(text)


def show_player(src, height):
    """Show a player in an iframe: a Spotify embed URL, or the Deezer player HTML from media.py.
    If anything goes wrong it is simply not shown."""
    if not src:
        return
    try:
        st.iframe(src, height=height)
    except Exception:
        pass


# Failures raise and are therefore not cached. Deezer's preview links are signed and only
# valid for about 15 minutes, so search results are kept for just 5.
@st.cache_data(ttl=300, show_spinner=False)
def online_search(query):
    return search_songs(query)


@st.cache_data(ttl=3600, show_spinner=False)
def online_features(isrc):
    return fetch_features(isrc)


def recommend_from_online(query, country):
    """For a song that is not in the dataset: pick it from a Deezer search, get its
    audio features and recommend. Returns (results, features, name), or None after
    showing a Korean message if anything goes wrong."""
    try:
        with st.spinner("온라인에서 곡을 찾는 중…"):
            choices = online_search(query)
        picked = st.selectbox(
            f"어떤 곡인가요? ({len(choices)}곡 검색됨)",
            range(len(choices)),
            format_func=lambda i: f"{choices[i]['title']} - {choices[i]['artist']}",
        )
        st.caption("내가 고른 곡 미리듣기")
        show_player(media.deezer_player_html(choices[picked]["preview"], choices[picked]["cover"]), media.DEEZER_PLAYER_HEIGHT)
        show_links(media.listen_links(choices[picked]["artist"], choices[picked]["title"], deezer_link=choices[picked]["link"]))
        with st.spinner("곡의 분위기를 분석하는 중…"):
            features, spotify_id = online_features(choices[picked]["isrc"])
    except LookupFailed as e:
        st.error(f"{LOOKUP_ERRORS[e.code]} 대신 슬라이더로 분위기를 정해 보세요.")
        return None
    if spotify_id and (df["track_id"] == spotify_id).any():  # it was in our data after all
        return rec.recommend(spotify_id, country, N_RESULTS, style=True, **MATCH), features, "내가 고른 곡"
    return rec.recommend_from_mood(features, country, N_RESULTS, **MATCH), features, "내가 고른 곡"


def song_label(row):
    return f"{row.track_name} - {row.artists.replace(';', ', ')}  [{row.genres.replace(';', ', ')}]"


def chart_values(values, bounds):
    """Map raw feature values to 0-1 so all bars share one axis."""
    out = {}
    for col, name in CHART_FEATURES:
        if col not in values:
            continue
        v = values[col]
        if col in RESCALED:
            lo, hi = bounds[col]
            v = min(max((v - lo) / (hi - lo), 0.0), 1.0)
        out[name] = float(v)
    return out


def comparison_chart(mine, other, mine_name, other_name):
    names = [n for _, n in CHART_FEATURES if n in mine]
    data = pd.DataFrame(
        [
            {"특성": n, "곡": label, "값": series[n]}
            for label, series in ((mine_name, mine), (other_name, other))
            for n in names
        ]
    )
    return (
        alt.Chart(data)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("특성:N", sort=names, title=None, axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("곡:N", sort=[mine_name, other_name]),
            y=alt.Y("값:Q", scale=alt.Scale(domain=[0, 1]), title="낮음 ↔ 높음"),
            color=alt.Color(
                "곡:N",
                sort=[mine_name, other_name],
                scale=alt.Scale(domain=[mine_name, other_name], range=SERIES_COLORS),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=["특성", "곡", alt.Tooltip("값:Q", format=".2f")],
        )
        .properties(height=300)
    )


st.set_page_config(page_title="Find Similar Songs")
st.title("Find Similar Songs")
st.write("좋아하는 노래 하나로, 다른 나라의 비슷한 노래를 만나보세요.")

rec = load_recommender()
df = rec.df
bounds = {c: (df[c].quantile(0.01), df[c].quantile(0.99)) for c in RESCALED}

query = st.text_input("노래 제목이나 가수 이름", placeholder="예: Someone Like You")
countries = COUNTRY_ORDER_FIRST + [c for c in rec.countries if c not in COUNTRY_ORDER_FIRST]
country = st.selectbox("나라 선택", countries, format_func=COUNTRY_LABELS.get)

if not query.strip():
    st.info("노래 제목이나 가수 이름을 입력하면 시작할 수 있어요.")
    st.stop()

found = rec.search(query)
if found.empty:
    st.warning(f"“{query}”는 데이터에 없는 곡이에요. 온라인에서 찾아볼게요.")
    st.caption("※ 데이터에 없는 곡은 비공식 무료 서비스(Deezer, ReccoBeats)로 찾기 때문에 가끔 작동하지 않을 수 있어요.")
    online = recommend_from_online(query, country)
    if online:
        results, my_values, my_name = online
    else:
        st.subheader("분위기를 직접 정해 볼까요?")
        st.caption("슬라이더로 원하는 분위기를 정해서 추천받을 수 있어요.")
        mood = {
            "valence": st.slider("밝기", 0.0, 1.0, 0.5, 0.05, help="낮을수록 어둡고 슬픈 느낌, 높을수록 밝고 행복한 느낌"),
            "energy": st.slider("에너지", 0.0, 1.0, 0.5, 0.05, help="높을수록 강렬하고 시끄러운 느낌"),
            "danceability": st.slider("댄스성", 0.0, 1.0, 0.5, 0.05, help="높을수록 춤추기 좋은 리듬"),
            "acousticness": st.slider("어쿠스틱", 0.0, 1.0, 0.5, 0.05, help="높을수록 전자음 없이 악기 소리 중심"),
            "tempo": st.slider("템포 (BPM)", 60, 200, 120, 5),
        }
        results = rec.recommend_from_mood(mood, country, N_RESULTS, **MATCH)
        my_values = mood
        my_name = "내가 정한 분위기"
else:
    songs = {row.track_id: row for row in found.itertuples()}
    track_id = st.selectbox(
        f"어떤 곡인가요? ({len(found)}곡 검색됨, 인기순)",
        list(songs),
        format_func=lambda tid: song_label(songs[tid]),
    )
    st.caption("내가 고른 곡 듣기")
    show_player(media.spotify_embed_url(track_id), media.EMBED_HEIGHT + 8)
    show_links(media.listen_links(songs[track_id].artists, songs[track_id].track_name, track_id=track_id))
    results = rec.recommend(track_id, country, N_RESULTS, style=True, **MATCH)
    my_values = df.loc[df["track_id"] == track_id, [c for c, _ in CHART_FEATURES]].iloc[0].to_dict()
    my_name = "내가 고른 곡"

country_name = COUNTRY_LABELS[country]
st.subheader(f"{country_name} 음악 중 분위기가 비슷한 곡")
if results.empty:
    st.warning(f"{country_name}에서 추천할 수 있는 곡이 없어요.")
    st.stop()

try:  # album covers; if they cannot be loaded the table just has no cover column
    cover_urls = media.covers(list(results["track_id"]))
except Exception:
    cover_urls = {}
table_rows = []
for tid, title, artists in zip(results["track_id"], results["track_name"], results["artists"]):
    links = dict(media.listen_links(artists, title, track_id=tid))
    table_rows.append({
        "title": title, "artist": artists.replace(";", ", "), "cover": cover_urls.get(tid),
        "play_url": links.get("Spotify"), "play_label": "Spotify에서 듣기", "youtube_url": links.get("YouTube"),
    })
try:  # a custom HTML table: round play button + YouTube icon (Streamlit's own table cannot draw them)
    theme = getattr(st.context.theme, "type", None) or "light"
except Exception:
    theme = "light"
try:
    st.iframe(results_table.build(table_rows, theme), height=results_table.height(len(table_rows)))
except Exception:  # fall back to a plain table without icons
    plain = pd.DataFrame({"제목": results["track_name"].values, "가수": results["artists"].str.replace(";", ", ").values})
    plain.index = range(1, len(plain) + 1)
    plain.index.name = "순위"
    st.dataframe(plain, width="stretch")
st.caption("비슷한 순서대로 보여드려요.")

st.subheader("왜 이 곡일까요?")
rows = results.reset_index(drop=True)
pick = st.selectbox(
    "비교해 볼 추천 곡을 고르세요",
    range(len(rows)),
    format_func=lambda i: f"{i + 1}위  {rows.loc[i, 'track_name']} - {rows.loc[i, 'artists'].replace(';', ', ')}",
)
other_values = rows.loc[pick, [c for c, _ in CHART_FEATURES]].to_dict()
other_name = f"{pick + 1}위 추천 곡"
chart_col, player_col = st.columns([3, 2])
with chart_col:
    st.altair_chart(
        comparison_chart(
            chart_values(my_values, bounds), chart_values(other_values, bounds), my_name, other_name
        ),
        width="stretch",
    )
    st.caption("템포와 음량은 전체 곡 기준으로 0~1 사이로 환산해 보여드려요.")
with player_col:
    st.caption(f"{pick + 1}위 추천 곡 듣기")
    show_player(media.spotify_embed_url(rows.loc[pick, "track_id"]), media.EMBED_HEIGHT + 8)
    show_links(media.listen_links(rows.loc[pick, "artists"], rows.loc[pick, "track_name"], track_id=rows.loc[pick, "track_id"]))

st.divider()
st.caption(
    "※ 나라는 곡의 장르 태그로 추정한 값이에요. 한국, 일본, 영어권은 직접 검토했고, "
    "다른 나라는 검토하지 않아서 그 나라 곡이 아닌 곡이 섞여 있을 수 있어요."
)
st.caption("※ 미리듣기와 앨범 커버는 Spotify와 Deezer에서 불러와요. 불러오지 못하면 보이지 않을 수 있어요.")
