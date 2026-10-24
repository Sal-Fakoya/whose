"""Item detail, hidden-detail verification, and pickup instructions.

This is the only screen that calls ai.judge_answer, and only inside the form submit handler.
Passing the hidden-detail check moves the item to pending_pickup and records a verified
claimant, but never claims the item. A session that has verified an item may then see the
pickup details, the finder's contact (for kept items), and a sensitive item's photo.
"""

from __future__ import annotations

import streamlit as st

from whose import ai, config, db, verify
from whose.views import _ui

_STATUS_LABEL = {
    db.STATUS_UNCLAIMED: "Unclaimed",
    db.STATUS_PENDING: "Pending pickup (still claimable)",
    db.STATUS_RETRIEVED: "Retrieved",
}


def _goto(view: str, **state) -> None:
    for key, value in state.items():
        st.session_state[key] = value
    st.session_state["view"] = view
    st.rerun()


def _is_verified(item_id: int) -> bool:
    return item_id in st.session_state.get("verified_items", set())


def _mark_verified(item_id: int) -> None:
    st.session_state.setdefault("verified_items", set()).add(item_id)


def _render_photo(item: dict, *, reveal: bool) -> None:
    """Show the photo. Sensitive photos are shown only when `reveal` is True."""
    if item.get("sensitive") and not reveal:
        st.markdown("**Photo hidden** until you verify this item is yours.")
        return
    _ui.safe_image(item.get("image_path"), width=260)


def _render_pickup_details(item: dict) -> None:
    """Show where to pick up, who to contact, and what to bring (after verification)."""
    st.success("Verified. You've earned the right to pick this item up in person.")

    st.markdown("#### Where to pick it up")
    if item.get("holder_type") == db.HOLDER_FINDER:
        contact = item.get("finder_contact") or "the finder"
        st.markdown(
            f"The finder is holding this item. Contact them to arrange pickup:  \n"
            f"**{contact}**"
        )
    else:
        loc = config.get_location(item.get("location_id"))
        if loc:
            st.markdown(
                f"**{loc['name']}**  \n"
                f"{loc['building']}  \n"
                f"Phone: {loc['phone']} · Email: {loc['email']}  \n"
                f"Hours: {loc['hours']}"
            )
        else:
            st.info("Pickup location details are unavailable.")

    st.markdown("#### What to bring")
    for thing in verify.what_to_bring(item):
        st.markdown(f"- {thing}")

    st.caption(
        "Passing this check does not claim the item. The holder checks your ID in person "
        "and decides. Others may also be verifying."
    )


def render() -> None:
    item_id = st.session_state.get("selected_item_id")
    if not item_id:
        _goto("lost")
        return
    item_id = int(item_id)

    conn = db.get_conn()
    try:
        row = db.get_item(conn, item_id)
    finally:
        conn.close()
    if row is None:
        st.error("That item could not be found.")
        if st.button("Back to search", icon=":material/arrow_back:"):
            _goto("lost")
        return

    item = db.item_to_dict(row)
    already_verified = _is_verified(item_id)

    if st.button("Back to search", icon=":material/arrow_back:"):
        _goto("lost")

    # Title: sensitive items stay generic until verified.
    if item.get("sensitive") and not already_verified:
        st.header("Sensitive item (details withheld)")
    else:
        st.header(item.get("description") or "Found item")

    st.caption(_STATUS_LABEL.get(item.get("status", ""), item.get("status", "")))
    _render_photo(item, reveal=already_verified)
    st.caption(f"Found: {item.get('where_found') or 'location not given'}")

    # Already verified this session -> show pickup details, no re-verify.
    if already_verified:
        _render_pickup_details(item)
        return

    # Retrieved items accept no verification.
    if item.get("status") == db.STATUS_RETRIEVED:
        st.info(
            "This item has already been picked up. If you believe yours was taken by "
            "someone else, contact the Lost & Found desk."
        )
        return

    st.divider()
    st.markdown("#### Is this yours? Verify with the hidden detail")
    st.caption(
        "The finder recorded a detail only the owner would know. Describe it in your own "
        "words. An exact match isn't required."
    )

    demo_mode = config.get_demo_mode()
    allowed_domains = config.allowed_email_domains(demo_mode)
    if demo_mode:
        st.info(config.DEMO_VERIFY_NOTICE)

    email_label = (
        "Your email *" if demo_mode else "Your UT Dallas email *"
    )
    email_placeholder = (
        "you@gmail.com" if demo_mode else "you@utdallas.edu"
    )

    with st.form("verify_form"):
        name = st.text_input("Your name *")
        email = st.text_input(email_label, placeholder=email_placeholder)
        answer = st.text_area("What's the hidden detail? *")
        submitted = st.form_submit_button("Verify")

    if not submitted:
        return

    conn = db.get_conn()
    try:
        hidden_detail = db.get_hidden_detail(conn, item_id) or ""
        result = verify.attempt(
            conn,
            item,
            name,
            email,
            answer,
            hidden_detail,
            ai.judge_answer,
            allowed_domains=allowed_domains,
        )
    finally:
        conn.close()

    if result.outcome == verify.PASS:
        _mark_verified(item_id)
        # Reload so status/photo reflect the new pending state, then show details.
        _goto("item", selected_item_id=item_id)
        return

    if result.outcome == verify.RATE_LIMITED:
        st.warning(result.message)
    elif result.outcome == verify.AI_ERROR:
        st.warning(result.message)
    elif result.outcome in (verify.LOCKED, verify.NOT_CLAIMABLE):
        st.error(result.message)
    else:  # FAIL, INVALID_EMAIL, MISSING_FIELDS
        st.error(result.message)
