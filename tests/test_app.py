from pathlib import Path

from streamlit.testing.v1 import AppTest

from countries import COUNTRY_GENRES

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_country_dropdown_order():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    box = at.selectbox[0]
    assert box.label == "나라 선택"
    assert box.options[:4] == ["한국", "일본", "영어권", "중국"]
    assert box.options[4:] == ["홍콩", "인도", "이란", "튀르키예", "말레이시아", "브라질", "프랑스어", "독일", "스웨덴", "스페인어"]
    assert len(box.options) == len(COUNTRY_GENRES) + 1  # every country, English-language included
    assert box.value == "South Korea"  # the key stays unchanged; only the label is Korean
    # the keys behind the labels still work: pick 영어권 and search a song
    at.text_input[0].set_value("Someone Like You").run()
    at.selectbox[0].set_value("English-language").run()
    assert not at.exception and len(at.dataframe[0].value) == 10
