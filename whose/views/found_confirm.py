"""Confirmation screen after posting a found item.

Shows the chosen holder's details (for a pickup location) or the one-time handoff code
(for a finder who is keeping the item), with a clear "cannot be recovered" warning.
"""

from __future__ import annotations

import streamlit as st

from whose import config, db


def _goto(view: str) -> None:
    st.session_state["view"] = view
    st.rerun()


def render() -> None:
    item_id = st.session_state.get("selected_item_id")
    if not item_id:
        _goto("home")
        return

    conn = db.get_conn()
    try:
        row = db.get_item(conn, int(item_id))
    finally:
        conn.close()

    if row is None:
        _goto("home")
        return

    item = db.item_to_dict(row)
    st.header("Item posted")
    st.success("Thanks for helping return this item.")

    st.subheader(item["description"] or "Your item")

    if item["holder_type"] == db.HOLDER_FINDER:
        code = st.session_state.get("last_handoff_code") or item.get("handoff_code")
        st.markdown("You chose to **keep the item** until the owner picks it up.")
        st.markdown("#### Your handoff code")
        if code:
            st.code(code, language=None)
        st.warning(
            "Save this code now. It cannot be recovered. You'll enter it to confirm the "
            "handoff after you check the owner's student ID in person."
        )
    else:
        loc = config.get_location(item.get("location_id"))
        if loc:
            st.markdown("Drop the item off here so the owner can collect it:")
            st.markdown(
                f"**{loc['name']}**  \n"
                f"{loc['building']}  \n"
                f"Phone: {loc['phone']} · Email: {loc['email']}  \n"
                f"Hours: {loc['hours']}"
            )
        else:
            st.info("Pickup location details are unavailable.")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Post another item", use_container_width=True):
            st.session_state["last_handoff_code"] = None
            _goto("found")
    with col2:
        if st.button("Back to home", use_container_width=True):
            st.session_state["last_handoff_code"] = None
            _goto("home")
