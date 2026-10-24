"""Whose? entry point: page config, init db, seed, route by session_state['view'].

Streamlit reruns this whole script on every interaction. Keep it cheap: the database schema
and seed run once per process (guarded), navigation lives in session_state, and each view
module owns its own screen. The AI is never called here — only inside view form handlers.
"""

from __future__ import annotations

import streamlit as st

from whose import ai, db, seed
from whose.config import RESULT_COUNTS
from whose.views import desk, found, found_confirm, handoff, home, item, lost

# Default values for every navigation / UI state key (design: session_state table).
_DEFAULT_STATE: dict = {
    "view": "home",
    "selected_item_id": None,
    "search_text": "",
    "search_location": "",
    "search_count": RESULT_COUNTS[0],
    "search_results": None,
    "verified_items": set(),
    "last_handoff_code": None,
    "desk_authed": False,
}

# Map each view key to its render function.
_ROUTES = {
    "home": home.render,
    "found": found.render,
    "found_confirm": found_confirm.render,
    "lost": lost.render,
    "item": item.render,
    "desk": desk.render,
    "handoff": handoff.render,
}


@st.cache_resource
def _startup() -> bool:
    """Create the schema and seed demo items once per process. Cached across reruns."""
    conn = db.get_conn()
    try:
        db.init_db(conn)
        seed.maybe_seed(conn)
    finally:
        conn.close()
    return True


def _init_state() -> None:
    """Ensure every expected session_state key exists without clobbering set values."""
    for key, default in _DEFAULT_STATE.items():
        if key not in st.session_state:
            # Copy mutable defaults so sessions never share a container.
            st.session_state[key] = (
                default.copy() if isinstance(default, set) else default
            )


def go(view: str, **state) -> None:
    """Navigate to a view, optionally setting other state keys, then rerun."""
    st.session_state["view"] = view
    for key, value in state.items():
        st.session_state[key] = value
    st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Whose?",
        page_icon=":material/search:",
        layout="centered",
    )
    _startup()
    _init_state()

    # Operator warning if the Gemini key is missing or malformed. This is a local shape
    # check only (no network call); it helps catch a misconfigured deployment before a demo.
    key_status = ai.api_key_status()
    if key_status == "missing":
        st.warning(
            "AI is not configured: set GEMINI_API_KEY in the app's secrets. "
            "Verification will not work until it is set.",
            icon=":material/warning:",
        )
    elif key_status == "suspect":
        st.warning(
            "The configured GEMINI_API_KEY does not look like a Gemini API key "
            "(these start with AIza). Verification may fail. Create one at "
            "https://aistudio.google.com/apikey and set it in the app's secrets.",
            icon=":material/warning:",
        )

    view = st.session_state.get("view", "home")
    render = _ROUTES.get(view, home.render)
    render()


if __name__ == "__main__":
    main()
