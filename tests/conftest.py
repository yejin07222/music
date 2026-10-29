from unittest import mock

import pytest
import streamlit as st

import online_lookup


@pytest.fixture(autouse=True)
def no_real_online_search(request):
    """The app searches Deezer on every search; app tests never touch the network unless they patch it themselves."""
    st.cache_data.clear()  # cached online results must not leak from one test into the next
    if request.module.__name__.endswith("test_online_lookup"):
        yield
        return
    with mock.patch.object(online_lookup, "search_online", side_effect=online_lookup.LookupFailed("network")):
        yield
