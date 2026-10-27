"""Streamlit UI (Korean): find songs from a chosen country that sound like a song you like.

Run: streamlit run app.py
"""
import altair as alt
import pandas as pd
import streamlit as st

from recommender import Recommender

N_RESULTS = 10

# Display names only; the keys must match countries.COUNTRY_GENRES.
COUNTRY_LABELS = {
    "Japan": "일본 (J-pop, J-rock, 아이돌, 애니…)",
    "South Korea": "한국 (K-pop, 직접 검토함)",
    "China (Mandarin)": "중국 (만다린 팝)",
    "Hong Kong (Cantonese)": "홍콩 (칸토팝)",
    "India": "인도 (인도 음악)",
    "Iran": "이란 (이란 음악)",
    "Turkey": "튀르키예 (터키 음악)",
    "Malaysia": "말레이시아 (말레이 음악)",
    "Brazil": "브라질 (브라질 음악, MPB, 삼바, 파고지…)",
    "France": "프랑스 (프렌치 팝)",
    "Germany": "독일 (독일 음악)",
    "Sweden": "스웨덴 (스웨덴 음악)",
    "Spanish-language": "스페인어권 (스페인어 팝, 라티노, 살사, 탱고…)",
}

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


st.set_page_config(page_title="무드 매치", page_icon="🎧")
st.title("🎧 무드 매치")
st.write("좋아하는 노래와 분위기가 비슷한 곡을, 다른 나라 음악에서 찾아드려요.")

rec = load_recommender()
df = rec.df
bounds = {c: (df[c].quantile(0.01), df[c].quantile(0.99)) for c in RESCALED}

query = st.text_input("노래 제목이나 가수를 검색하세요", placeholder="예: Someone Like You")
country = st.selectbox("어느 나라 음악에서 찾을까요?", rec.countries, format_func=COUNTRY_LABELS.get)

if not query.strip():
    st.info("노래 제목이나 가수 이름을 입력하면 시작할 수 있어요.")
    st.stop()

found = rec.search(query)
if found.empty:
    st.warning(f"“{query}”에 해당하는 곡을 찾지 못했어요. 철자를 바꾸거나 제목 일부만 입력해 보세요.")
    st.subheader("분위기를 직접 정해 볼까요?")
    st.caption("곡을 찾지 못했을 때는 슬라이더로 원하는 분위기를 정해서 추천받을 수 있어요.")
    mood = {
        "valence": st.slider("밝기", 0.0, 1.0, 0.5, 0.05, help="낮을수록 어둡고 슬픈 느낌, 높을수록 밝고 행복한 느낌"),
        "energy": st.slider("에너지", 0.0, 1.0, 0.5, 0.05, help="높을수록 강렬하고 시끄러운 느낌"),
        "danceability": st.slider("댄스성", 0.0, 1.0, 0.5, 0.05, help="높을수록 춤추기 좋은 리듬"),
        "acousticness": st.slider("어쿠스틱", 0.0, 1.0, 0.5, 0.05, help="높을수록 전자음 없이 악기 소리 중심"),
        "tempo": st.slider("템포 (BPM)", 60, 200, 120, 5),
    }
    results = rec.recommend_from_mood(mood, country, N_RESULTS)
    my_values = mood
    my_name = "내가 정한 분위기"
else:
    songs = {row.track_id: row for row in found.itertuples()}
    track_id = st.selectbox(
        f"어떤 곡인가요? ({len(found)}곡 검색됨, 인기순)",
        list(songs),
        format_func=lambda tid: song_label(songs[tid]),
    )
    results = rec.recommend(track_id, country, N_RESULTS)
    my_values = df.loc[df["track_id"] == track_id, [c for c, _ in CHART_FEATURES]].iloc[0].to_dict()
    my_name = "내가 고른 곡"

country_name = COUNTRY_LABELS[country].split(" (")[0]
st.subheader(f"{country_name} 음악 중 분위기가 비슷한 곡")
if results.empty:
    st.warning(f"{country_name}에서 추천할 수 있는 곡이 없어요.")
    st.stop()

table = results[["track_name", "artists", "genres"]].reset_index(drop=True)
table.index = table.index + 1
table.index.name = "순위"
table.columns = ["제목", "가수", "장르"]
table["가수"] = table["가수"].str.replace(";", ", ")
table["장르"] = table["장르"].str.replace(";", ", ")
st.dataframe(table, width="stretch")
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
st.altair_chart(
    comparison_chart(
        chart_values(my_values, bounds), chart_values(other_values, bounds), my_name, other_name
    ),
    width="stretch",
)
st.caption("템포와 음량은 전체 곡 기준으로 0~1 사이로 환산해 보여드려요.")

st.divider()
st.caption(
    "※ 나라는 곡의 장르 태그로 추정한 값이에요. 직접 검토한 나라는 한국뿐이라 "
    "다른 나라에는 그 나라 곡이 아닌 곡이 섞여 있을 수 있어요."
)
