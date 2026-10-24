"""Pickup locations and app-wide constants. No Streamlit or AI imports here.

All contact details are obvious placeholders, never real-looking values.
"""

from __future__ import annotations

import secrets
from typing import TypedDict


class PickupLocation(TypedDict):
    """A campus desk that can hold found items."""

    id: str
    name: str
    building: str
    phone: str
    email: str
    hours: str


# Realistic UT Dallas desks with placeholder contact details only.
PICKUP_LOCATIONS: list[PickupLocation] = [
    {
        "id": "mcdermott",
        "name": "McDermott Library Service Desk",
        "building": "McDermott Library (MC), first floor",
        "phone": "972-555-0100",
        "email": "library-desk@example.edu",
        "hours": "Mon-Fri 8am-10pm, Sat-Sun 10am-8pm",
    },
    {
        "id": "student_union",
        "name": "Student Union Information Desk",
        "building": "Student Union (SU), main level",
        "phone": "972-555-0110",
        "email": "union-desk@example.edu",
        "hours": "Mon-Fri 9am-9pm, Sat 10am-6pm",
    },
    {
        "id": "rec_center",
        "name": "Activity Center Front Desk",
        "building": "Activity Center (AC), entrance lobby",
        "phone": "972-555-0120",
        "email": "rec-desk@example.edu",
        "hours": "Mon-Fri 6am-11pm, Sat-Sun 8am-8pm",
    },
    {
        "id": "ecss",
        "name": "ECSS Building Front Office",
        "building": "Engineering & Computer Science South (ECSS), room 2.1",
        "phone": "972-555-0130",
        "email": "ecss-office@example.edu",
        "hours": "Mon-Fri 8am-5pm",
    },
    {
        "id": "police",
        "name": "UTD Police Lost & Found",
        "building": "Police Services Building (PS)",
        "phone": "972-555-0140",
        "email": "lostandfound@example.edu",
        "hours": "Open 24 hours",
    },
]

# Sentinel holder option for a finder who keeps the item themselves.
HOLDER_KEEPING = "keeping"

# Verification attempt limits.
MAX_ATTEMPTS_PER_EMAIL = 3          # per item, per claimant email
ITEM_REVIEW_CAP = 10                # total failed attempts -> flag item for desk review

# Search result counts offered to owners. Applies to each section separately.
RESULT_COUNTS = [5, 10, 15]

# Only UT Dallas email addresses may start a claim.
UTD_EMAIL_DOMAIN = "@utdallas.edu"

# Email domains accepted on the verification form.
#
# The live app only accepts UT Dallas addresses. Demo mode additionally accepts a
# common consumer domain so the flow can be shown without a real UTD account.
# Keep allowed domains here, never hardcoded in views.
LIVE_EMAIL_DOMAINS: tuple[str, ...] = (UTD_EMAIL_DOMAIN,)
DEMO_EMAIL_DOMAINS: tuple[str, ...] = (UTD_EMAIL_DOMAIN, "@gmail.com")

# Notices shown when demo mode is on. No emojis.
DEMO_VERIFY_NOTICE = (
    "Demo mode: Gmail addresses are accepted for testing. "
    "The live app requires a UTD email."
)
DEMO_HOME_NOTICE = "Demo mode"

# What a claimant must bring to pick up a high-value item (student ID is always required).
HIGH_VALUE_BRING = "proof of purchase or serial number"

# Handoff code: 8 characters, uppercase letters + digits, excluding the ambiguous
# characters O, 0, I, and 1 so codes are easy to read aloud and type.
HANDOFF_CODE_LEN = 8
HANDOFF_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def get_desk_passcode() -> str | None:
    """Read DESK_PASSCODE from st.secrets or the environment. Never hardcoded.

    Returns None if it is not configured, so the desk view can show a setup notice
    instead of silently allowing access.
    """
    try:
        import streamlit as st

        value = st.secrets.get("DESK_PASSCODE")  # type: ignore[attr-defined]
        if value:
            return str(value)
    except Exception:
        # Streamlit unavailable or no secrets file; fall back to the environment.
        pass
    import os

    value = os.environ.get("DESK_PASSCODE")
    return str(value) if value else None


def get_demo_mode() -> bool:
    """Read DEMO_MODE from st.secrets or the environment. Defaults to False.

    Accepts common truthy spellings ("1", "true", "yes", "on"), case-insensitive.
    Any other value, or an unset key, means demo mode is off.
    """
    raw: object = None
    try:
        import streamlit as st

        raw = st.secrets.get("DEMO_MODE")  # type: ignore[attr-defined]
    except Exception:
        # Streamlit unavailable or no secrets file; fall back to the environment.
        raw = None
    if raw is None:
        import os

        raw = os.environ.get("DEMO_MODE")
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def allowed_email_domains(demo_mode: bool | None = None) -> tuple[str, ...]:
    """Return the email domains accepted on the verification form.

    When demo_mode is None it is resolved from secrets/env via get_demo_mode.
    Live mode allows only the UTD domain; demo mode also allows Gmail.
    """
    if demo_mode is None:
        demo_mode = get_demo_mode()
    return DEMO_EMAIL_DOMAINS if demo_mode else LIVE_EMAIL_DOMAINS


def get_location(location_id: str | None) -> PickupLocation | None:
    """Return the pickup location with this id, or None if not found."""
    if not location_id:
        return None
    for location in PICKUP_LOCATIONS:
        if location["id"] == location_id:
            return location
    return None


def new_handoff_code() -> str:
    """Generate a cryptographically random 8-character handoff code.

    Drawn with secrets.choice from HANDOFF_CODE_ALPHABET (no ambiguous characters).
    The code is shown once and cannot be recovered afterward.
    """
    return "".join(
        secrets.choice(HANDOFF_CODE_ALPHABET) for _ in range(HANDOFF_CODE_LEN)
    )
