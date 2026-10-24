"""Post a found item: reference locations, form, image save, AI describe, handoff code.

Rerun discipline: the AI is called only inside the submit handler. The uploaded image is
saved to disk once on submit and its path is stashed in session_state, so an AI failure that
needs a resubmit never loses the upload. An item is never saved with a generic description.
"""

from __future__ import annotations

import os
import uuid

import streamlit as st

from whose import ai, config, db
from whose.views import _ui

# The uploads directory (relative path is what the DB stores).
_IMAGE_DIR = os.path.join(_ui.PROJECT_ROOT, "data", "images")


def _abs_image_path(relative_path: str) -> str:
    """Resolve a stored relative image path (e.g. data/images/x.jpg) to an absolute path."""
    return _ui.abs_image_path(relative_path)

# Session keys scoped to this flow.
_PENDING = "found_pending"  # dict of saved field values awaiting a successful save
_ERROR = "found_error"      # friendly message to show above the form


def _save_image_bytes(data: bytes, original_name: str) -> str | None:
    """Persist image bytes under data/images/<uuid>, return its relative path.

    Returns None if saving fails, so the caller can degrade gracefully.
    """
    try:
        os.makedirs(_IMAGE_DIR, exist_ok=True)
        suffix = os.path.splitext(original_name)[1].lower() or ".jpg"
        fname = f"{uuid.uuid4().hex}{suffix}"
        with open(os.path.join(_IMAGE_DIR, fname), "wb") as f:
            f.write(data)
        return os.path.join("data", "images", fname)
    except OSError:
        return None


def _mime_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")


def _holder_options() -> list[tuple[str, str]]:
    """(value, label) pairs for the holder selector."""
    opts = [(loc["id"], loc["name"]) for loc in config.PICKUP_LOCATIONS]
    opts.append((config.HOLDER_KEEPING, "I'm keeping it myself"))
    return opts


def _reference_locations() -> None:
    """Show all pickup locations above the form (no rerun needed to see details)."""
    with st.expander("Pickup locations and their contact details", expanded=False):
        for loc in config.PICKUP_LOCATIONS:
            st.markdown(
                f"**{loc['name']}** — {loc['building']}  \n"
                f"Phone: {loc['phone']} · Email: {loc['email']}  \n"
                f"Hours: {loc['hours']}"
            )
            st.divider()


def _finalize_and_save(fields: dict, image_bytes: bytes | None) -> bool:
    """Run the AI, apply the fallback rules, and save the item. Returns True on save.

    Rules (Req 2.1, 2.7, 2.8): call the AI once; on success persist its output; on AI
    failure use a non-empty short description; if the short description is empty, do NOT
    save — stash the fields so the form can be re-rendered and resubmitted.
    """
    image_path = fields["image_path"]
    short_desc = (fields.get("short_description") or "").strip()

    description = ""
    tags: list[str] = []
    sensitive = False
    high_value = False
    ai_failed = False

    try:
        if image_bytes is None:
            # The image was saved on a previous submit; re-read it for the AI call.
            with open(_abs_image_path(image_path), "rb") as f:
                image_bytes = f.read()
        result = ai.describe_item(image_bytes, _mime_for(image_path))
        description, tags = result.description, result.tags
        sensitive, high_value = result.sensitive, result.high_value
    except ai.AIRateLimitError:
        ai_failed = True
        st.session_state[_ERROR] = (
            "Our describer is busy right now. Add a short description below and try again "
            "in a minute."
        )
    except ai.AIError:
        ai_failed = True
        st.session_state[_ERROR] = (
            "We couldn't auto-describe the photo. Add a short description below so people "
            "can still find it, then post again."
        )

    if ai_failed:
        if not short_desc:
            # Do not save. Keep fields (incl. saved image) for a resubmit.
            st.session_state[_PENDING] = fields
            return False
        # Save using the finder's short description; safe defaults, sensitive=true.
        description, tags, sensitive, high_value = short_desc, [], True, False

    handoff_code = (
        config.new_handoff_code()
        if fields["holder_type"] == db.HOLDER_FINDER
        else None
    )
    conn = db.get_conn()
    try:
        item_id = db.insert_item(
            conn,
            where_found=fields["where_found"],
            holder_type=fields["holder_type"],
            hidden_detail=fields["hidden_detail"],
            location_id=fields.get("location_id"),
            finder_contact=fields.get("finder_contact"),
            handoff_code=handoff_code,
            image_path=image_path,
            description=description,
            tags=tags,
            sensitive=sensitive,
            high_value=high_value,
            short_description=short_desc or None,
        )
    finally:
        conn.close()

    # Hand off to the confirmation screen.
    st.session_state.pop(_PENDING, None)
    st.session_state.pop(_ERROR, None)
    st.session_state["selected_item_id"] = item_id
    st.session_state["last_handoff_code"] = handoff_code
    st.session_state["view"] = "found_confirm"
    return True


def render() -> None:
    st.header("Post a found item")
    st.caption("Help return something you found to its owner.")

    if st.button("Back to home", icon=":material/arrow_back:"):
        st.session_state.pop(_PENDING, None)
        st.session_state.pop(_ERROR, None)
        st.session_state["view"] = "home"
        st.rerun()

    _reference_locations()

    pending = st.session_state.get(_PENDING)
    if st.session_state.get(_ERROR):
        st.warning(st.session_state[_ERROR])

    # If an image was already saved on a prior submit, show it and skip re-upload.
    saved_image_path = pending.get("image_path") if pending else None
    if saved_image_path:
        _ui.safe_image(saved_image_path, width=240)
        st.caption("Your uploaded photo (saved)")

    st.info(
        "Do not photograph the hidden detail. Keep it to yourself — the owner proves the "
        "item is theirs by describing it, and we never show it to anyone."
    )

    options = _holder_options()
    values = [v for v, _ in options]
    labels = {v: lbl for v, lbl in options}

    with st.form("found_form", clear_on_submit=False):
        uploaded = None
        if not saved_image_path:
            uploaded = st.file_uploader(
                "Photo of the item *",
                type=["jpg", "jpeg", "png", "gif", "webp"],
            )

        where_found = st.text_input(
            "Where did you find it? *",
            value=(pending or {}).get("where_found", ""),
        )
        holder = st.selectbox(
            "Who is holding it now? *",
            options=values,
            format_func=lambda v: labels[v],
            index=(
                values.index(pending["holder_raw"])
                if pending and pending.get("holder_raw") in values
                else 0
            ),
        )
        finder_contact = st.text_input(
            "Your contact (required if you're keeping it)",
            value=(pending or {}).get("finder_contact", "") or "",
        )
        short_description = st.text_input(
            "Short description (optional — used if auto-describe is unavailable)",
            value=(pending or {}).get("short_description", "") or "",
        )
        hidden_detail = st.text_area(
            "Hidden detail only the owner would know *",
            value=(pending or {}).get("hidden_detail", ""),
            help="Something not visible in the photo, e.g. a sticker inside, initials, "
            "or what's in a pocket.",
        )
        submitted = st.form_submit_button("Post item")

    if not submitted:
        return

    # ---- validation (Req 1.5, 1.6) ----
    errors = []
    if not saved_image_path and uploaded is None:
        errors.append("a photo")
    if not where_found.strip():
        errors.append("where you found it")
    if not hidden_detail.strip():
        errors.append("a hidden detail")
    keeping = holder == config.HOLDER_KEEPING
    if keeping and not finder_contact.strip():
        errors.append("your contact (required when you keep the item)")

    if errors:
        st.error("Please provide: " + ", ".join(errors) + ".")
        return

    # ---- save the image once (Req 1.7) ----
    image_bytes: bytes | None = None
    if saved_image_path:
        image_path = saved_image_path
    else:
        image_bytes = bytes(uploaded.getbuffer())
        image_path = _save_image_bytes(image_bytes, uploaded.name)
        if image_path is None:
            st.error("Sorry, we couldn't save that image. Please try another photo.")
            return

    holder_type = db.HOLDER_FINDER if keeping else db.HOLDER_LOCATION
    location_id = None if keeping else holder

    fields = {
        "where_found": where_found.strip(),
        "holder_type": holder_type,
        "holder_raw": holder,
        "location_id": location_id,
        "finder_contact": finder_contact.strip() or None,
        "short_description": short_description.strip(),
        "hidden_detail": hidden_detail.strip(),
        "image_path": image_path,
    }

    if _finalize_and_save(fields, image_bytes):
        st.rerun()
    else:
        # AI failed and no short description: re-render with values preserved.
        st.rerun()
