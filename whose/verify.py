"""Hidden-detail verification, attempt limits, and status changes. No Streamlit.

The AI judge is injected as `judge_fn` so this module is testable without the SDK.
`judge_fn(hidden_detail, answer) -> bool` may raise ai.AIError / ai.AIRateLimitError.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from . import config, db
from .ai import AIError, AIRateLimitError

# A judge takes (hidden_detail, answer) and returns True on a semantic match.
JudgeFn = Callable[[str, str], bool]

# Outcome codes for a verification attempt.
PASS = "PASS"
FAIL = "FAIL"
LOCKED = "LOCKED"
INVALID_EMAIL = "INVALID_EMAIL"
MISSING_FIELDS = "MISSING_FIELDS"
AI_ERROR = "AI_ERROR"
RATE_LIMITED = "RATE_LIMITED"
NOT_CLAIMABLE = "NOT_CLAIMABLE"


@dataclass
class VerifyResult:
    """The outcome of a verification attempt and the data a view needs to respond."""

    outcome: str
    message: str = ""
    attempts_remaining: int | None = None
    claimant_id: int | None = None
    what_to_bring: list[str] = field(default_factory=list)
    flagged_for_review: bool = False

    @property
    def passed(self) -> bool:
        return self.outcome == PASS


def email_is_valid(
    email: str | None, allowed_domains: Sequence[str] | None = None
) -> bool:
    """True if the email ends with one of the allowed domains and has a sane local part.

    `allowed_domains` defaults to the live set (UTD only). In demo mode the caller passes
    the demo set so Gmail addresses are also accepted. Allowed domains live in config,
    never hardcoded here.
    """
    if not email:
        return False
    domains = tuple(allowed_domains) if allowed_domains else config.LIVE_EMAIL_DOMAINS
    normalized = email.strip().lower()
    matched = next((d for d in domains if normalized.endswith(d)), None)
    if matched is None:
        return False
    local = normalized[: -len(matched)]
    # Require a non-empty local part with no spaces.
    return bool(local) and " " not in local


def _domains_phrase(domains: Sequence[str]) -> str:
    """Human-readable 'ending in X' or 'ending in X or Y' for an error message."""
    cleaned = list(domains)
    if len(cleaned) == 1:
        return f"ending in {cleaned[0]}"
    if len(cleaned) == 2:
        return f"ending in {cleaned[0]} or {cleaned[1]}"
    return "ending in " + ", ".join(cleaned[:-1]) + f", or {cleaned[-1]}"


def email_locked(conn: sqlite3.Connection, item_id: int, email: str) -> bool:
    """True if this email has used up its attempts for this item."""
    return (
        db.count_attempts(conn, item_id, email) >= config.MAX_ATTEMPTS_PER_EMAIL
    )


def what_to_bring(item: Mapping[str, Any]) -> list[str]:
    """What a claimant must bring to pick up: student ID always; proof for high-value."""
    items = ["a valid student ID"]
    if item.get("high_value"):
        items.append(config.HIGH_VALUE_BRING)
    return items


def attempt(
    conn: sqlite3.Connection,
    item: Mapping[str, Any],
    name: str,
    email: str,
    answer: str,
    hidden_detail: str,
    judge_fn: JudgeFn,
    allowed_domains: Sequence[str] | None = None,
) -> VerifyResult:
    """Run one verification attempt for `item` using the injected judge.

    `hidden_detail` is passed in explicitly by the caller (from db.get_hidden_detail)
    so it never travels inside the public `item` mapping that views render.

    Order of checks (per design):
      1. Required fields present.
      2. Email is a valid UTD address (no AI, no attempt recorded on failure).
      3. Item is still claimable (unclaimed or pending_pickup).
      4. Email not already locked (no AI).
      5. Call judge_fn; AI error / 429 returns without recording an attempt.
      6. Match -> move unclaimed to pending_pickup, add verified claimant, PASS.
      7. No match -> record failed attempt, flag for desk review at the per-item cap, FAIL.
    """
    item_id = int(item["id"])
    name = (name or "").strip()
    email = (email or "").strip()
    answer = (answer or "").strip()
    domains = tuple(allowed_domains) if allowed_domains else config.LIVE_EMAIL_DOMAINS

    # 1. Required fields.
    if not name or not email or not answer:
        return VerifyResult(
            MISSING_FIELDS,
            message="Please enter your name, UTD email, and an answer.",
        )

    # 2. Email validity (before any AI call or attempt record).
    if not email_is_valid(email, domains):
        return VerifyResult(
            INVALID_EMAIL,
            message=f"Please use a valid email address ({_domains_phrase(domains)}).",
        )

    # 3. Claimable status. Retrieved items accept no new attempts.
    status = str(item.get("status", ""))
    if status not in (db.STATUS_UNCLAIMED, db.STATUS_PENDING):
        return VerifyResult(
            NOT_CLAIMABLE,
            message="This item has already been picked up.",
        )

    # 4. Per-email lock.
    if email_locked(conn, item_id, email):
        return VerifyResult(
            LOCKED,
            message="This email has used all its attempts for this item. "
            "Please contact the Lost & Found desk.",
            attempts_remaining=0,
        )

    # 5. Ask the judge. AI failures never consume an attempt.
    try:
        matched = judge_fn(hidden_detail or "", answer)
    except AIRateLimitError:
        return VerifyResult(
            RATE_LIMITED,
            message="We're a bit busy right now. Please try again in a minute.",
        )
    except AIError:
        return VerifyResult(
            AI_ERROR,
            message="Something went wrong checking your answer. Please try again.",
        )

    # 6. Match: advance status if needed and record the verified claimant.
    if matched:
        if status == db.STATUS_UNCLAIMED:
            db.set_status(conn, item_id, db.STATUS_PENDING)
        claimant_id = db.add_verified_claimant(conn, item_id, name, email)
        return VerifyResult(
            PASS,
            message="Verified. Here's where to pick it up and what to bring.",
            claimant_id=claimant_id,
            what_to_bring=what_to_bring(item),
        )

    # 7. No match: record the failed attempt, maybe flag for desk review.
    db.record_failed_attempt(conn, item_id, email)
    total = db.count_attempts(conn, item_id)
    flagged = total >= config.ITEM_REVIEW_CAP
    if flagged:
        db.set_flagged_for_review(conn, item_id)

    used_by_email = db.count_attempts(conn, item_id, email)
    remaining = max(0, config.MAX_ATTEMPTS_PER_EMAIL - used_by_email)
    if remaining == 0:
        message = (
            "That didn't match, and this email has used all its attempts. "
            "Please contact the Lost & Found desk."
        )
    else:
        plural = "attempt" if remaining == 1 else "attempts"
        message = f"That didn't match. You have {remaining} {plural} left."
    return VerifyResult(
        FAIL,
        message=message,
        attempts_remaining=remaining,
        flagged_for_review=flagged,
    )
