"""Finder enters a handoff code to mark an item retrieved.

Two steps: enter the code to look up the item (invalid codes change nothing), then review the
verified claimants, pick who collected it, and confirm the in-person handoff. Confirming sets
the item to retrieved and records which claimant picked it up (or none, as an edge case).
"""

from __future__ import annotations

import streamlit as st

from whose import db

# Flow-scoped session key: the item id matched by a valid handoff code.
_MATCHED = "handoff_matched_item_id"


def _goto(view: str) -> None:
    st.session_state["view"] = view
    st.rerun()


def _clear_flow() -> None:
    st.session_state.pop(_MATCHED, None)


def _code_entry() -> None:
    """Step 1: look up an item by handoff code."""
    st.caption(
        "Enter the handoff code you received when you chose to keep the item. "
        "Check the owner's student ID in person before confirming."
    )
    with st.form("handoff_code_form"):
        code = st.text_input("Handoff code")
        submitted = st.form_submit_button("Look up item")

    if not submitted:
        return
    if not code.strip():
        st.error("Please enter your handoff code.")
        return

    conn = db.get_conn()
    try:
        row = db.find_item_by_handoff_code(conn, code)
    finally:
        conn.close()

    if row is None:
        st.error("No active item matches that code. Nothing was changed.")
        return

    st.session_state[_MATCHED] = int(row["id"])
    st.rerun()


def _confirm_step(item_id: int) -> None:
    """Step 2: show claimants, pick who collected it, confirm retrieval."""
    conn = db.get_conn()
    try:
        row = db.get_item(conn, item_id)
        claimants = list(db.list_claimants(conn, item_id))
    finally:
        conn.close()

    if row is None or row["status"] == db.STATUS_RETRIEVED:
        st.info("This item is no longer available for handoff.")
        _clear_flow()
        if st.button("Enter another code"):
            st.rerun()
        return

    item = db.item_to_dict(row)
    st.success("Code accepted.")
    st.subheader(item.get("description") or "Your item")
    st.caption(f"Found: {item.get('where_found') or 'n/a'}")

    if claimants:
        st.markdown("**Verified claimants** (match against their student ID):")
        for c in claimants:
            st.markdown(f"- {c['name']} · {c['email']}")
    else:
        st.caption("No one has verified this item yet.")

    labels = ["No claimant on file"] + [f"{c['name']} · {c['email']}" for c in claimants]
    ids = [None] + [c["id"] for c in claimants]
    choice = st.selectbox(
        "Who is picking it up?",
        options=list(range(len(labels))),
        format_func=lambda i: labels[i],
        index=1 if claimants else 0,
    )

    st.warning(
        "Only confirm after you've checked the owner's student ID (plus proof of purchase "
        "or a serial number for a high-value item)."
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Confirm handoff and mark retrieved", use_container_width=True):
            conn = db.get_conn()
            try:
                db.mark_retrieved(conn, item_id, ids[choice])
            finally:
                conn.close()
            _clear_flow()
            st.session_state["handoff_done"] = True
            st.rerun()
    with col2:
        if st.button("Cancel", use_container_width=True):
            _clear_flow()
            st.rerun()


def render() -> None:
    st.header("Confirm a handoff")

    if st.button("Back to home", icon=":material/arrow_back:"):
        _clear_flow()
        st.session_state.pop("handoff_done", None)
        _goto("home")

    if st.session_state.pop("handoff_done", False):
        st.success("Handoff confirmed. The item is now marked retrieved. Thank you!")
        if st.button("Confirm another handoff"):
            st.rerun()
        return

    matched = st.session_state.get(_MATCHED)
    if matched:
        _confirm_step(int(matched))
    else:
        _code_entry()
