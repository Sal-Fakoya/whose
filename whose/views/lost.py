"""Search for a lost item: 5/10/15 selector, two ranked result sections.

Ranking is AI-free (whose.matching), so search is instant and never rate-limited. The search
text stays in the form for easy re-querying, and inputs/results live in session_state so a
rerun never repeats work. Sensitive items hide their photo behind a placeholder; the finder's
personal contact and the hidden detail are never shown here.
"""

from __future__ import annotations

import streamlit as st

from whose import config, db, matching
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


def _render_photo(item: dict) -> None:
    """Show the item's photo, or a placeholder for sensitive items / missing files."""
    if item.get("sensitive"):
        st.markdown("**Photo hidden** — shown only after you verify this is yours.")
        return
    _ui.safe_image(item.get("image_path"), width=220)


def _render_contact(item: dict) -> None:
    """Show the public pickup contact. Never the finder's personal contact."""
    if item.get("holder_type") == db.HOLDER_FINDER:
        st.caption(
            "Held by the finder. Their contact is shared only after you verify ownership."
        )
        return
    loc = config.get_location(item.get("location_id"))
    if loc:
        st.markdown(
            f"**Pick up at: {loc['name']}**  \n"
            f"{loc['building']}  \n"
            f"Phone: {loc['phone']} · Email: {loc['email']}  \n"
            f"Hours: {loc['hours']}"
        )
    else:
        st.caption("Pickup location details are unavailable.")


def _render_match(match: matching.Match, *, claimable: bool) -> None:
    item = match.item
    with st.container(border=True):
        cols = st.columns([1, 2])
        with cols[0]:
            _render_photo(item)
        with cols[1]:
            title = item.get("description") or "Found item"
            if item.get("sensitive"):
                title = "Sensitive item (details withheld)"
            st.markdown(f"**{title}**")
            st.caption(_STATUS_LABEL.get(item.get("status", ""), item.get("status", "")))
            st.markdown(f"_{match.reason}_")
            _render_contact(item)
            if claimable:
                if st.button(
                    "This might be mine. Verify",
                    key=f"claim_{item['id']}",
                    use_container_width=True,
                ):
                    _goto("item", selected_item_id=item["id"])


def _run_search(query: str, location: str, count: int) -> None:
    """Rank items (no AI) and store the two capped sections in session_state."""
    conn = db.get_conn()
    try:
        rows = [db.item_to_dict(r) for r in db.list_items_for_search(conn)]
    finally:
        conn.close()
    ranked = matching.rank(query, location, rows)
    active, retrieved = matching.split_sections(ranked, count)
    st.session_state["search_results"] = {
        "active": [(m.item, m.reason) for m in active],
        "retrieved": [(m.item, m.reason) for m in retrieved],
    }


def _results_from_state() -> tuple[list[matching.Match], list[matching.Match]]:
    """Rebuild Match objects from the stored results so rendering is rerun-stable."""
    data = st.session_state.get("search_results") or {"active": [], "retrieved": []}
    active = [matching.Match(item=i, score=0.0, reason=r) for i, r in data["active"]]
    retrieved = [matching.Match(item=i, score=0.0, reason=r) for i, r in data["retrieved"]]
    return active, retrieved


def render() -> None:
    st.header("Search for a lost item")

    if st.button("Back to home", icon=":material/arrow_back:"):
        st.session_state["view"] = "home"
        st.rerun()

    with st.form("lost_form"):
        query = st.text_area(
            "Describe what you lost, in your own words *",
            value=st.session_state.get("search_text", ""),
            placeholder="e.g. a black water bottle with stickers",
        )
        location = st.text_input(
            "Where do you think you lost it? (optional)",
            value=st.session_state.get("search_location", ""),
        )
        count = st.radio(
            "How many results per section?",
            options=config.RESULT_COUNTS,
            index=config.RESULT_COUNTS.index(
                st.session_state.get("search_count", config.RESULT_COUNTS[0])
            ),
            horizontal=True,
        )
        submitted = st.form_submit_button("Search")

    if submitted:
        # Keep inputs in the form for re-querying.
        st.session_state["search_text"] = query.strip()
        st.session_state["search_location"] = location.strip()
        st.session_state["search_count"] = count
        if not query.strip():
            st.error("Please describe what you lost.")
            st.session_state["search_results"] = None
        else:
            _run_search(query.strip(), location.strip(), count)

    if st.session_state.get("search_results") is None:
        return

    active, retrieved = _results_from_state()

    st.subheader("Unclaimed")
    st.caption("Items nobody has collected yet. Pending items are still claimable.")
    if active:
        for m in active:
            _render_match(m, claimable=True)
    else:
        st.info("No unclaimed matches. Try different words or fewer details.")

    st.subheader("Already retrieved")
    st.caption(
        "Items already picked up. If you believe yours was taken by someone else, contact "
        "the Lost & Found desk."
    )
    if retrieved:
        for m in retrieved:
            _render_match(m, claimable=False)
    else:
        st.info("No retrieved matches.")
