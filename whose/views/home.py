"""Home screen: headline, how it works, live stats, recent finds, and entry points.

All data here comes from plain SQLite count/list queries. The AI is never called on this
screen. Primary actions (found / lost) are large; holder actions (desk / handoff) sit in a
small row at the bottom. No emojis anywhere.
"""

from __future__ import annotations

import streamlit as st

from whose import config, db
from whose.views import _ui


def _goto(view: str, **state) -> None:
    for key, value in state.items():
        st.session_state[key] = value
    st.session_state["view"] = view
    st.rerun()


def _load_home_data() -> tuple[int, int, list[dict]]:
    """Read live stats and recent unclaimed public items in one connection."""
    conn = db.get_conn()
    try:
        waiting = db.count_claimable_items(conn)
        returned = db.count_retrieved_items(conn)
        recent = [db.item_to_dict(r) for r in db.list_recent_unclaimed_public(conn, 4)]
    finally:
        conn.close()
    return waiting, returned, recent


def _render_how_it_works() -> None:
    """Three short steps, side by side."""
    st.markdown("#### How it works")
    cols = st.columns(3)
    steps = [
        ("1. Post a photo", "Found something? Snap a photo and say who is holding it."),
        ("2. Search your words", "Lost something? Describe it plainly and see ranked matches."),
        (
            "3. Prove and pick up",
            "Answer a hidden detail only the owner would know, then collect it with "
            "your student ID.",
        ),
    ]
    for col, (title, body) in zip(cols, steps):
        with col:
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.caption(body)


def _render_stats(waiting: int, returned: int) -> None:
    """Live counts from the database. No AI."""
    cols = st.columns(2)
    with cols[0]:
        st.metric("Waiting to be claimed", waiting)
    with cols[1]:
        st.metric("Items returned", returned)


def _render_recent(recent: list[dict]) -> None:
    """Up to four newest unclaimed, non-sensitive items with a small View button."""
    if not recent:
        return
    st.markdown("#### Recently found")
    cols = st.columns(len(recent))
    for col, item in zip(cols, recent):
        with col:
            with st.container(border=True):
                _ui.safe_image(item.get("image_path"), width=150)
                title = item.get("description") or "Found item"
                st.caption(title)
                if st.button(
                    "View",
                    key=f"home_view_{item['id']}",
                    use_container_width=True,
                    icon=":material/visibility:",
                ):
                    _goto("item", selected_item_id=item["id"])


# UT Dallas accent colors: orange primary comes from .streamlit/config.toml; this
# minimal CSS adds the green accent (page title and stat values) and tints links green.
_HOME_CSS = """
<style>
h1 { color: #e87500; }
div[data-testid="stMetricValue"] { color: #154734; }
a, a:visited { color: #154734; }
</style>
"""


def render() -> None:
    """Render the landing page."""
    st.markdown(_HOME_CSS, unsafe_allow_html=True)

    if config.get_demo_mode():
        st.caption(config.DEMO_HOME_NOTICE)

    st.title("Lost it on campus? Find it here.")
    st.write(
        "Whose? is a peer-to-peer lost and found for UT Dallas, where students return "
        "what they find and owners prove an item is theirs before picking it up."
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "I found something",
            use_container_width=True,
            type="primary",
            icon=":material/add_a_photo:",
        ):
            _goto("found")
    with col2:
        if st.button(
            "I lost something",
            use_container_width=True,
            type="primary",
            icon=":material/search:",
        ):
            _goto("lost")

    st.divider()
    _render_how_it_works()

    waiting, returned, recent = _load_home_data()

    st.divider()
    _render_stats(waiting, returned)

    if recent:
        st.divider()
        _render_recent(recent)

    st.divider()
    st.caption("For holders")
    cols = st.columns(2)
    with cols[0]:
        if st.button(
            "Lost and Found desk",
            use_container_width=True,
            icon=":material/desk:",
        ):
            _goto("desk")
    with cols[1]:
        if st.button(
            "I kept an item (handoff)",
            use_container_width=True,
            icon=":material/key:",
        ):
            _goto("handoff")
