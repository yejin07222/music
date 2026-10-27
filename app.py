"""Streamlit UI (Korean): find songs from a chosen country that sound like a song you like.

Run: streamlit run app.py
"""
import html

import altair as alt
import pandas as pd
import streamlit as st

import media
import results_table
from countries import ALL_COUNTRIES
from recommender import Recommender
from online_lookup import LookupFailed, fetch_features, search_songs

N_RESULTS = 10
# Matching used by the app: Euclidean distance on weighted features, plus a style bonus when the
# input song's genres are known (see NOTES.md section 8).
MATCH = {"method": "euclid", "weighted": True}

# Display names only; the keys must match countries.COUNTRY_GENRES.
COUNTRY_LABELS = {
    ALL_COUNTRIES: "전체",
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
COUNTRY_ORDER_FIRST = [ALL_COUNTRIES, "South Korea", "Japan", "English-language", "China (Mandarin)"]

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

# Height in px of everything in the comparison box except the chart (picker, subtitle, legend, divider,
# label, player, paddings and gaps; measured in a browser at about 360-385); the chart gets the rest of the list's
# height, a little less to be safe.
CHART_BOX_OVERHEAD = 390

MY_COLOR, RESULT_COLOR = "#A9B8F0", "#2F49C8"  # light navy = my song, navy = the result
SERIES_COLORS = [MY_COLOR, RESULT_COLOR]


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


def show_song_card(title, artist, cover, play_url, play_label, youtube_url):
    """The card for the song the user picked; if it cannot be shown it is simply left out."""
    try:
        st.iframe(
            results_table.song_card({
                "title": title, "artist": artist.replace(";", ", "), "cover": cover,
                "play_url": play_url, "play_label": play_label, "youtube_url": youtube_url,
            }),
            height=results_table.CARD_HEIGHT,
        )
    except Exception:
        pass


def song_cover(track_id, artists, title):
    try:
        return media.covers([track_id], info={track_id: (artists, title)}).get(track_id)
    except Exception:
        return None


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


def recommend_from_online(query, country, picker_slot, card_slot, player_slot, notice_slot):
    """For a song that is not in the dataset: pick it from a Deezer search, get its
    audio features and recommend. The picker, card and player go into their slots on the page.
    Returns (results, features, name, title), or None after showing a Korean message if anything goes wrong."""
    try:
        with st.spinner("온라인에서 곡을 찾는 중…"):
            choices = online_search(query)
        with picker_slot:
            picked = st.selectbox(
                f"어떤 곡인가요? ({len(choices)}곡 검색됨)",
                range(len(choices)),
                format_func=lambda i: f"{choices[i]['title']} - {choices[i]['artist']}",
            )
        choice = choices[picked]
        with card_slot:
            show_song_card(
                choice["title"], choice["artist"], choice["cover"], media.deezer_track_url(choice["link"]),
                "Deezer에서 듣기", media.youtube_search_url(choice["artist"], choice["title"]),
            )
        with player_slot:
            st.caption("내가 고른 곡 미리듣기")
            show_player(media.deezer_player_html(choice["preview"], choice["cover"]), media.DEEZER_PLAYER_HEIGHT)
        with st.spinner("곡의 분위기를 분석하는 중…"):
            features, spotify_id = online_features(choice["isrc"])
    except LookupFailed as e:
        with notice_slot:
            st.error(f"{LOOKUP_ERRORS[e.code]} 대신 슬라이더로 분위기를 정해 보세요.")
        return None
    if spotify_id and (df["track_id"] == spotify_id).any():  # it was in our data after all
        return rec.recommend(spotify_id, country, N_RESULTS, style=True, **MATCH), features, "내가 고른 곡", choice["title"]
    return rec.recommend_from_mood(features, country, N_RESULTS, **MATCH), features, "내가 고른 곡", choice["title"]


def song_label(row):
    return f"{row.track_name} - {row.artists.replace(';', ', ')}"


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


def comparison_chart(mine, other, mine_name, other_name, height=None):
    """Horizontal bars, one pair per feature, feature names on the left."""
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
        .mark_bar(cornerRadiusEnd=6, size=11)
        .encode(
            y=alt.Y("특성:N", sort=names, title=None,
                    axis=alt.Axis(domain=False, ticks=False, labelPadding=12, labelFontSize=13, labelColor="#222222",
                                  labelLimit=0, minExtent=84)),  # reserve room so labels like 어쿠스틱 are not cut
            yOffset=alt.YOffset("곡:N", sort=[mine_name, other_name]),
            x=alt.X("값:Q", scale=alt.Scale(domain=[0, 1]), title=None, axis=None),  # no numbers, no grid lines
            color=alt.Color("곡:N", sort=[mine_name, other_name],
                            scale=alt.Scale(domain=[mine_name, other_name], range=SERIES_COLORS), legend=None),
            tooltip=["특성", "곡", alt.Tooltip("값:Q", format=".2f")],
        )
        .properties(height=height or 46 * len(names))
        .configure_view(stroke=None)
        .configure(font="Noto Sans KR")
    )


# Fonts and the few styles Streamlit's theme (.streamlit/config.toml) cannot set: only the title uses
# Pretendard, everything else Noto Sans KR. The title's word "Similar" is navy.
# The @NAME@ values are the sizes from results_table.py (see the comments there).
PAGE_CSS_TEMPLATE = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');
.stApp, .stApp p, .stApp label, .stApp li, .stApp input, .stApp textarea, .stApp button, .stApp [data-baseweb] {
    font-family: 'Noto Sans KR', system-ui, -apple-system, 'Segoe UI', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
}
h1.app-title { font-family: 'Pretendard', 'Noto Sans KR', system-ui, -apple-system, sans-serif;
    font-size: 2.3rem; font-weight: 800; letter-spacing: -0.02em; color: #222222; margin: 0.4rem 0 0.2rem; padding: 0; }
.stApp h1.app-title, .stApp h1.app-title * { color: #222222 !important; }
.stApp h1.app-title span.accent { color: #3B5BDB !important; }
.stApp [data-testid="stCaptionContainer"] { color: #777777; }

/* Second row: pin the label, the boxes and the gap to known sizes so that the "my song" card on the right
   (offset by @CARD_TOP@px, @CARD_HEIGHT@px high) starts level with the top of the boxes and ends level with
   the bottom of the picker box. */
.stApp .st-key-inputs { gap: @ROW_GAP@px; }
.stApp .st-key-inputs [data-testid="stWidgetLabel"] { height: @LABEL_H@px; min-height: @LABEL_H@px; margin-bottom: @LABEL_GAP@px; overflow: hidden; }
.stApp .st-key-inputs [data-testid="stWidgetLabel"] p { margin: 0; line-height: @LABEL_H@px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stApp .st-key-inputs div[data-baseweb="input"], .stApp .st-key-inputs div[data-baseweb="select"] > div { height: @BOX_H@px; min-height: @BOX_H@px; }
.stApp .st-key-mycard { margin-top: @CARD_TOP@px; }

/* Third row: both headings look the same so the list and the box start on the same line. The "분위기 비교" box
   has the same background, border and radius as the results list box (results_table.py); its minimum height is
   set to the list's height at the end of the page, and the content is spread out to fill it. */
.sec-title { font-size: 1.15rem; font-weight: 700; color: #222222; margin: 0 0 0.15rem; }
.stApp .st-key-compare { display: flex; flex-direction: column; justify-content: space-between; gap: 12px;
    background: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 14px; padding: 14px; box-sizing: border-box; }
.sec-sub { font-size: 0.85rem; color: #777777; }
.legend { font-size: 0.85rem; color: #222222; margin: 0.35rem 0 0; }
.legend span.item { margin-right: 14px; white-space: nowrap; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin: 0 5px 1px 0; }
.thin-divider { border-top: 1px solid #E5E5EA; height: 0; margin: 0; }

/* Responsive. From 1200px up: the two main rows are 3:2 columns. Below 1200px (half screen, phone): one column,
   in the order title, inputs, my song card, results list, "분위기 비교" box. Streamlit's own columns only stack
   below ~640px, so the two main rows (st-key-row2, st-key-row3) are stacked here; the search|country pair keeps
   Streamlit's default (side by side until 640px). */
@media (max-width: 1199px) {
    .stApp .st-key-row2 > div > [data-testid="stHorizontalBlock"], .stApp .st-key-row3 > div > [data-testid="stHorizontalBlock"] {
        flex-direction: column; flex-wrap: nowrap; }
    .stApp .st-key-row2 > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
    .stApp .st-key-row3 > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        width: 100% !important; min-width: 100% !important; flex: 1 1 100% !important; }
    .stApp .st-key-mycard { margin-top: 0; }                    /* stacked: nothing to line up with */
    .stApp .st-key-compare { min-height: 0 !important; }        /* stacked: no need to match the list's height */
    .stApp [data-testid="stMainBlockContainer"] { padding-left: 2rem; padding-right: 2rem; }
}
@media (max-width: 640px) {                                      /* phone: smaller side padding */
    .stApp [data-testid="stMainBlockContainer"] { padding-left: 1rem; padding-right: 1rem; padding-top: 3rem; }
    h1.app-title { font-size: 1.9rem; }
}
</style>
"""


def page_css():
    sizes = {
        "CARD_TOP": results_table.CARD_TOP, "CARD_HEIGHT": results_table.CARD_HEIGHT, "ROW_GAP": results_table.ROW_GAP,
        "LABEL_H": results_table.LABEL_H, "LABEL_GAP": results_table.LABEL_GAP, "BOX_H": results_table.BOX_H,
    }
    css = PAGE_CSS_TEMPLATE
    for name, value in sizes.items():
        css = css.replace(f"@{name}@", str(value))
    return css


st.set_page_config(page_title="Find Similar Songs", layout="wide")  # must be the first Streamlit call
st.markdown(page_css(), unsafe_allow_html=True)

# Row 1 (full width): title and subtitle
st.markdown(
    '<h1 class="app-title" style="color:#222222">Find <span class="accent" style="color:#3B5BDB">Similar</span> Songs</h1>',
    unsafe_allow_html=True,
)
st.write("좋아하는 노래 하나로, 다른 나라의 비슷한 노래를 만나보세요.")

rec = load_recommender()
df = rec.df
bounds = {c: (df[c].quantile(0.01), df[c].quantile(0.99)) for c in RESCALED}

# Row 2 (3:2): the inputs on the left, the "my song" card on the right (stacked on narrow screens)
with st.container(key="row2"):
    inputs_col, card_col = st.columns([3, 2])
with inputs_col:
    with st.container(key="inputs"):
        search_col, country_col = st.columns([2, 1])  # search box and country dropdown side by side
        with search_col:
            query = st.text_input("노래 제목이나 가수 이름", placeholder="예: Someone Like You")
        with country_col:
            countries = COUNTRY_ORDER_FIRST + [c for c in rec.countries if c not in COUNTRY_ORDER_FIRST]
            country = st.selectbox("나라 선택", countries, format_func=COUNTRY_LABELS.get)
        picker_slot = st.container()  # the song picker goes here, below the two boxes
with card_col:
    card_slot = st.container(key="mycard")  # the card; its top is level with the top of the boxes
    player_slot = st.container()  # the embedded player under the card
notice_slot = st.container()  # messages and the mood sliders, full width under the row

if not query.strip():
    st.stop()

found = rec.search(query)
if found.empty:
    with notice_slot:
        st.warning(f"“{query}”는 데이터에 없는 곡이에요. 온라인에서 찾아볼게요.")
        st.caption("※ 데이터에 없는 곡은 비공식 무료 서비스(Deezer, ReccoBeats)로 찾기 때문에 가끔 작동하지 않을 수 있어요.")
    online = recommend_from_online(query, country, picker_slot, card_slot, player_slot, notice_slot)
    if online:
        results, my_values, my_name, my_title = online
    else:
        with notice_slot:
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
        my_name = my_title = "내가 정한 분위기"
else:
    songs = {row.track_id: row for row in found.itertuples()}
    with picker_slot:
        track_id = st.selectbox(
            f"어떤 곡인가요? ({len(found)}곡 검색됨, 인기순)",
            list(songs),
            format_func=lambda tid: song_label(songs[tid]),
        )
    song = songs[track_id]
    with card_slot:
        show_song_card(
            song.track_name, song.artists, song_cover(track_id, song.artists, song.track_name), media.spotify_track_url(track_id),
            "Spotify에서 듣기", media.youtube_search_url(song.artists, song.track_name),
        )
    results = rec.recommend(track_id, country, N_RESULTS, style=True, **MATCH)
    my_values = df.loc[df["track_id"] == track_id, [c for c, _ in CHART_FEATURES]].iloc[0].to_dict()
    my_name = "내가 고른 곡"
    my_title = song.track_name

# Row 3 (3:2), aligned at the top: the results list on the left, the comparison box on the right
country_name = COUNTRY_LABELS[country]
with st.container(key="row3"):
    list_col, compare_col = st.columns([3, 2])
with list_col:
    st.markdown(f'<div class="sec-title">{html.escape(country_name)} 음악 중 분위기가 비슷한 곡</div>', unsafe_allow_html=True)
    if results.empty:
        st.warning(f"{country_name}에서 추천할 수 있는 곡이 없어요.")
        st.stop()
    try:  # album covers; if they cannot be loaded the list just has no covers
        cover_urls = media.covers(
            list(results["track_id"]),
            info={t: (a, n) for t, a, n in zip(results["track_id"], results["artists"], results["track_name"])},
        )
    except Exception:
        cover_urls = {}
    list_rows = []
    for tid, title, artists in zip(results["track_id"], results["track_name"], results["artists"]):
        links = dict(media.listen_links(artists, title, track_id=tid))
        list_rows.append({
            "title": title, "artist": artists.replace(";", ", "), "cover": cover_urls.get(tid),
            "play_url": links.get("Spotify"), "play_label": "Spotify에서 듣기", "youtube_url": links.get("YouTube"),
        })
    list_h = results_table.list_height(len(list_rows))
    try:  # a custom HTML list: rank badge, cover, YouTube button and round play button
        st.iframe(results_table.results_list(list_rows), height=list_h)
    except Exception:  # fall back to a plain table without icons
        plain = pd.DataFrame({"제목": results["track_name"].values, "가수": results["artists"].str.replace(";", ", ").values})
        plain.index = range(1, len(plain) + 1)
        plain.index.name = "순위"
        st.dataframe(plain, width="stretch")
    st.caption("비슷한 순서대로 보여드려요.")

rows = results.reset_index(drop=True)
with compare_col:
    st.markdown('<div class="sec-title">분위기 비교</div>', unsafe_allow_html=True)
    with st.container(key="compare"):  # one rounded box, as tall as the results list
        pick = st.selectbox(
            "비교해 볼 추천 곡을 고르세요",
            range(len(rows)),
            format_func=lambda i: f"{i + 1}위  {rows.loc[i, 'track_name']} - {rows.loc[i, 'artists'].replace(';', ', ')}",
        )
        other_values = rows.loc[pick, [c for c, _ in CHART_FEATURES]].to_dict()
        other_name = f"{pick + 1}위 추천 곡"
        st.markdown(  # the subtitle on one line, the legend on its own line below
            f'<div class="sec-sub">{html.escape(my_title)} vs {pick + 1}위 {html.escape(rows.loc[pick, "track_name"])}</div>'
            '<div class="legend">'
            f'<span class="item"><span class="dot" style="background:{MY_COLOR}"></span>{html.escape(my_name)}</span>'
            f'<span class="item"><span class="dot" style="background:{RESULT_COLOR}"></span>{html.escape(other_name)}</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        st.altair_chart(
            comparison_chart(
                chart_values(my_values, bounds), chart_values(other_values, bounds), my_name, other_name,
                height=max(200, list_h - CHART_BOX_OVERHEAD),
            ),
            width="stretch",
        )
        st.markdown('<div class="thin-divider"></div>', unsafe_allow_html=True)
        st.caption(f"{pick + 1}위 곡 미리듣기")
        show_player(media.spotify_embed_url(rows.loc[pick, "track_id"]), media.EMBED_HEIGHT + 8)

st.divider()
st.caption(
    "※ 나라는 곡의 장르 태그로 추정한 값이에요. 한국, 일본, 영어권은 직접 검토했고, "
    "다른 나라는 검토하지 않아서 그 나라 곡이 아닌 곡이 섞여 있을 수 있어요."
)
st.caption("※ 분위기 비교에서 템포와 음량은 전체 곡 기준으로 0~1 사이로 환산해 보여드려요.")
st.caption("※ 미리듣기와 앨범 커버는 Spotify와 Deezer에서 불러와요. 불러오지 못하면 보이지 않을 수 있어요.")

# The comparison box is at least as tall as the results list, so the bottom edges line up. Put last so that
# this (invisible) element does not add a gap in the columns above.
st.markdown(
    f"<style>.stApp .st-key-compare {{ min-height: {list_h}px; }}</style>", unsafe_allow_html=True
)
