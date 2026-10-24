"""Tests for whose.verify. No Streamlit, no real SDK — the judge is a fake callable.

Note: prompt-injection resistance is NOT unit-tested here. A fake judge would only exercise
the fake's own rule, not the real Gemini prompt, so injection resistance is verified manually
against the live model in task 15.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from whose import config, db, verify
from whose.ai import AIError, AIRateLimitError


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """A fresh SQLite database per test, isolated under a temp directory."""
    db_path = os.path.join(tmp_path, "whose.db")
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "_DATA_DIR", str(tmp_path))
    c = db.get_conn()
    db.init_db(c)
    yield c
    c.close()


def _new_item(conn, *, high_value=False, status=db.STATUS_UNCLAIMED) -> dict:
    """Insert an item and return its public dict (no hidden detail)."""
    iid = db.insert_item(
        conn,
        where_found="MC library",
        holder_type=db.HOLDER_LOCATION,
        location_id="mcdermott",
        hidden_detail="cat sticker on the lid",
        description="black water bottle",
        tags=["bottle", "flask"],
        high_value=high_value,
        status=status,
    )
    return db.item_to_dict(db.get_item(conn, iid))


# Judges with fixed behavior.
def judge_match(_hidden, _answer):
    return True


def judge_no_match(_hidden, _answer):
    return False


def judge_raises_rate_limit(_hidden, _answer):
    raise AIRateLimitError("429")


def judge_raises_ai_error(_hidden, _answer):
    raise AIError("boom")


# --- email validation ---------------------------------------------------------


@pytest.mark.parametrize(
    "email,expected",
    [
        ("student@utdallas.edu", True),
        ("Student@UTDallas.edu", True),
        ("student@gmail.com", False),
        ("@utdallas.edu", False),
        ("has space@utdallas.edu", False),
        ("", False),
        (None, False),
    ],
)
def test_email_is_valid_live_default(email, expected):
    """With no allowed_domains, only UTD addresses are valid (live behavior)."""
    assert verify.email_is_valid(email) is expected


@pytest.mark.parametrize(
    "email,expected",
    [
        ("student@utdallas.edu", True),
        ("student@gmail.com", True),
        ("Student@Gmail.com", True),
        ("student@yahoo.com", False),
        ("@gmail.com", False),
        ("has space@gmail.com", False),
    ],
)
def test_email_is_valid_demo_domains(email, expected):
    """In demo mode, Gmail is also accepted; other domains are still rejected."""
    assert (
        verify.email_is_valid(email, config.DEMO_EMAIL_DOMAINS) is expected
    )


def test_attempt_rejects_gmail_in_live_mode(conn):
    item = _new_item(conn)
    res = verify.attempt(
        conn, item, "Jordan", "jordan@gmail.com", "cat", "hd", judge_match,
        allowed_domains=config.LIVE_EMAIL_DOMAINS,
    )
    assert res.outcome == verify.INVALID_EMAIL
    assert db.count_attempts(conn, item["id"]) == 0


def test_attempt_accepts_gmail_in_demo_mode(conn):
    item = _new_item(conn)
    res = verify.attempt(
        conn, item, "Jordan", "jordan@gmail.com", "a cat sticker",
        "cat sticker on the lid", judge_match,
        allowed_domains=config.DEMO_EMAIL_DOMAINS,
    )
    assert res.outcome == verify.PASS
    assert len(db.list_claimants(conn, item["id"])) == 1


# --- pass path -----------------------------------------------------------------


def test_pass_creates_claimant_and_moves_to_pending(conn):
    item = _new_item(conn)
    res = verify.attempt(
        conn, item, "Jordan", "jordan@utdallas.edu", "a cat sticker",
        "cat sticker on the lid", judge_match,
    )
    assert res.outcome == verify.PASS
    assert res.passed
    assert res.claimant_id is not None
    # Status advanced and a claimant recorded.
    assert db.item_to_dict(db.get_item(conn, item["id"]))["status"] == db.STATUS_PENDING
    assert len(db.list_claimants(conn, item["id"])) == 1
    # A pass records no failed attempt.
    assert db.count_attempts(conn, item["id"]) == 0


def test_pass_on_pending_item_keeps_pending_and_adds_another_claimant(conn):
    item = _new_item(conn, status=db.STATUS_PENDING)
    res = verify.attempt(
        conn, item, "Sam", "sam@utdallas.edu", "cat", "cat sticker", judge_match,
    )
    assert res.passed
    assert db.item_to_dict(db.get_item(conn, item["id"]))["status"] == db.STATUS_PENDING


# --- validation short-circuits -------------------------------------------------


def test_missing_fields_blocks_without_ai_or_attempt(conn):
    item = _new_item(conn)
    res = verify.attempt(conn, item, "", "jordan@utdallas.edu", "", "hd", judge_match)
    assert res.outcome == verify.MISSING_FIELDS
    assert db.count_attempts(conn, item["id"]) == 0


def test_invalid_email_blocks_without_attempt(conn):
    item = _new_item(conn)
    res = verify.attempt(
        conn, item, "Jordan", "jordan@gmail.com", "cat", "hd", judge_match,
    )
    assert res.outcome == verify.INVALID_EMAIL
    assert db.count_attempts(conn, item["id"]) == 0


def test_retrieved_item_is_not_claimable(conn):
    item = _new_item(conn, status=db.STATUS_RETRIEVED)
    res = verify.attempt(
        conn, item, "Jordan", "jordan@utdallas.edu", "cat", "hd", judge_match,
    )
    assert res.outcome == verify.NOT_CLAIMABLE
    assert db.count_attempts(conn, item["id"]) == 0


# --- fail path, lock, and desk-review flag ------------------------------------


def test_fail_records_attempt_and_reports_remaining(conn):
    item = _new_item(conn)
    res = verify.attempt(
        conn, item, "Jordan", "jordan@utdallas.edu", "wrong", "hd", judge_no_match,
    )
    assert res.outcome == verify.FAIL
    assert res.attempts_remaining == config.MAX_ATTEMPTS_PER_EMAIL - 1
    assert db.count_attempts(conn, item["id"], "jordan@utdallas.edu") == 1


def test_email_locks_after_three_failures(conn):
    item = _new_item(conn)
    email = "jordan@utdallas.edu"
    for _ in range(config.MAX_ATTEMPTS_PER_EMAIL):
        verify.attempt(conn, item, "Jordan", email, "wrong", "hd", judge_no_match)
    # Fourth attempt is locked out, no further attempt recorded.
    res = verify.attempt(conn, item, "Jordan", email, "wrong", "hd", judge_no_match)
    assert res.outcome == verify.LOCKED
    assert res.attempts_remaining == 0
    assert db.count_attempts(conn, item["id"], email) == config.MAX_ATTEMPTS_PER_EMAIL


def test_item_flagged_for_review_at_cap(conn):
    item = _new_item(conn)
    # Burn attempts across many distinct emails (3 each) until the per-item cap.
    emails = [f"u{i}@utdallas.edu" for i in range(5)]  # up to 15 attempts available
    flagged_seen = False
    for email in emails:
        for _ in range(config.MAX_ATTEMPTS_PER_EMAIL):
            res = verify.attempt(conn, item, "U", email, "wrong", "hd", judge_no_match)
            if res.outcome == verify.FAIL and res.flagged_for_review:
                flagged_seen = True
    assert db.count_attempts(conn, item["id"]) >= config.ITEM_REVIEW_CAP
    assert flagged_seen
    assert db.item_to_dict(db.get_item(conn, item["id"]))["flagged_for_review"] == 1


# --- AI errors never consume an attempt ---------------------------------------


def test_rate_limit_does_not_consume_attempt(conn):
    item = _new_item(conn)
    res = verify.attempt(
        conn, item, "Jordan", "jordan@utdallas.edu", "x", "hd",
        judge_raises_rate_limit,
    )
    assert res.outcome == verify.RATE_LIMITED
    assert db.count_attempts(conn, item["id"]) == 0


def test_ai_error_does_not_consume_attempt(conn):
    item = _new_item(conn)
    res = verify.attempt(
        conn, item, "Jordan", "jordan@utdallas.edu", "x", "hd",
        judge_raises_ai_error,
    )
    assert res.outcome == verify.AI_ERROR
    assert db.count_attempts(conn, item["id"]) == 0


# --- what to bring -------------------------------------------------------------


def test_what_to_bring_student_id_only_for_normal_item(conn):
    item = _new_item(conn, high_value=False)
    assert verify.what_to_bring(item) == ["a valid student ID"]


def test_what_to_bring_adds_proof_for_high_value(conn):
    item = _new_item(conn, high_value=True)
    bring = verify.what_to_bring(item)
    assert "a valid student ID" in bring
    assert config.HIGH_VALUE_BRING in bring
