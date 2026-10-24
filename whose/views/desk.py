"""Passcode-protected desk view: pending list, mark retrieved, archive.

Staff unlock with the desk passcode (from st.secrets / env, never hardcoded). They see each
pending item's verified claimants so they can match a claimant against the student ID at
pickup, mark an item retrieved (recording which claimant collected it), and archive retrieved
items so they drop out of search and active lists.
"""

from __future__ import annotations

import streamlit as st

from whose import config, db
from whose.views import _ui


def _goto(view: str) -> None:
    st.session_state["view"] = view
    st.rerun()


def _passcode_gate() -> bool:
    """Render the passcode form. Returns True once this session is authenticated."""
    if st.session_state.get("desk_authed"):
        return True

    passcode = config.get_desk_passcode()
    if not passcode:
        st.error(
            "The desk passcode is not configured. Set DESK_PASSCODE in secrets or the "
            "environment."
        )
        return False

    with st.form("desk_passcode_form"):
        entered = st.text_input("Desk passcode", type="password")
        submitted = st.form_submit_button("Unlock")

    if submitted:
        if entered == passcode:
            st.session_state["desk_authed"] = True
            st.rerun()
        else:
            st.error("Incorrect passcode.")
    return False


def _render_claimants(item_id: int) -> list:
    """List verified claimants for an item; returns the claimant rows."""
    conn = db.get_conn()
    try:
        claimants = db.list_claimants(conn, item_id)
    finally:
        conn.close()
    if claimants:
        st.markdown("**Verified claimants** (match against student ID):")
        for c in claimants:
            st.markdown(f"- {c['name']} · {c['email']}")
    else:
        st.caption("No verified claimants yet.")
    return list(claimants)


def _render_pending_item(item: dict) -> None:
    with st.container(border=True):
        cols = st.columns([1, 2])
        with cols[0]:
            if item.get("sensitive"):
                st.markdown("Sensitive")
            else:
                _ui.safe_image(item.get("image_path"), width=160)
        with cols[1]:
            title = (
                "Sensitive item"
                if item.get("sensitive")
                else (item.get("description") or "Found item")
            )
            st.markdown(f"**#{item['id']} — {title}**")
            st.caption(f"Found: {item.get('where_found') or 'n/a'}")
            if item.get("flagged_for_review"):
                st.warning("Flagged for desk review (many failed attempts).")

            claimants = _render_claimants(item["id"])

            # Build the claimant choices; allow "no claimant on file" as an edge case.
            labels = ["No claimant on file"] + [
                f"{c['name']} · {c['email']}" for c in claimants
            ]
            ids = [None] + [c["id"] for c in claimants]
            default_index = 1 if claimants else 0
            choice = st.selectbox(
                "Who is picking it up?",
                options=list(range(len(labels))),
                format_func=lambda i: labels[i],
                index=default_index,
                key=f"pickup_choice_{item['id']}",
            )
            if st.button("Mark retrieved", key=f"retrieve_{item['id']}"):
                conn = db.get_conn()
                try:
                    db.mark_retrieved(conn, item["id"], ids[choice])
                finally:
                    conn.close()
                st.rerun()


def _render_retrieved_item(item: dict) -> None:
    with st.container(border=True):
        title = (
            "Sensitive item"
            if item.get("sensitive")
            else (item.get("description") or "Found item")
        )
        st.markdown(f"**#{item['id']} — {title}**")
        st.caption(f"Retrieved: {item.get('retrieved_at') or 'n/a'}")
        claimant_id = item.get("retrieved_by_claimant_id")
        if claimant_id:
            conn = db.get_conn()
            try:
                claimants = {c["id"]: c for c in db.list_claimants(conn, item["id"])}
            finally:
                conn.close()
            c = claimants.get(claimant_id)
            if c:
                st.caption(f"Picked up by: {c['name']} · {c['email']}")
        else:
            st.caption("Picked up by: no claimant on file")
        if st.button("Archive", key=f"archive_{item['id']}"):
            conn = db.get_conn()
            try:
                db.archive_item(conn, item["id"])
            finally:
                conn.close()
            st.rerun()


def render() -> None:
    st.header("Lost and Found desk")

    if st.button("Back to home", icon=":material/arrow_back:"):
        _goto("home")

    if not _passcode_gate():
        return

    cols = st.columns([3, 1])
    with cols[1]:
        if st.button("Lock desk"):
            st.session_state["desk_authed"] = False
            st.rerun()

    conn = db.get_conn()
    try:
        pending = [db.item_to_dict(r) for r in db.list_pending_items(conn)]
        retrieved = [db.item_to_dict(r) for r in db.list_retrieved_items(conn)]
    finally:
        conn.close()

    st.subheader(f"Pending pickup ({len(pending)})")
    if pending:
        for item in pending:
            _render_pending_item(item)
    else:
        st.info("Nothing waiting for pickup right now.")

    st.divider()
    st.subheader(f"Retrieved — ready to archive ({len(retrieved)})")
    if retrieved:
        for item in retrieved:
            _render_retrieved_item(item)
    else:
        st.info("No retrieved items to archive.")
