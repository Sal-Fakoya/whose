"""Rank items against a lost-item description. No AI, no Streamlit.

Ranking uses token overlap between the owner's words and each item's public
description + tags, with a small boost when the owner's guessed location overlaps the
item's `where_found`. The hidden detail is never part of the ranking data.

Items are passed in as mappings (sqlite3.Row or dict) that must include at least
`id`, `status`, `description`, `tags`, and `where_found`. `tags` may be a JSON string
or a list; both are handled.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .db import STATUS_RETRIEVED

# Tokens shorter than this (after stripping) are ignored, except known short ones.
_MIN_TOKEN_LEN = 2

# Common words that carry no matching signal.
_STOPWORDS = {
    "a", "an", "the", "my", "mine", "is", "it", "its", "i", "me", "of", "for",
    "with", "and", "or", "to", "in", "on", "at", "by", "this", "that", "some",
    "lost", "found", "item", "thing", "somewhere", "think", "maybe", "near",
    "around", "left", "dropped", "missing", "please", "help",
}

# How much a location-word overlap contributes relative to a description/tag hit.
_LOCATION_WEIGHT = 0.5

# Extra weight when the query names the item's primary type (e.g. searching "laptop" for a
# laptop). This nudges the most on-type items above incidental tag overlaps.
_PRIMARY_TYPE_WEIGHT = 1.0


@dataclass
class Match:
    """An item paired with its ranking score and a human-readable reason."""

    item: dict[str, Any]
    score: float
    reason: str

    @property
    def status(self) -> str:
        return str(self.item.get("status", ""))


def _tokenize(text: str | None) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords and tiny tokens."""
    if not text:
        return []
    raw = re.split(r"[^a-z0-9]+", text.lower())
    out: list[str] = []
    for tok in raw:
        if not tok or tok in _STOPWORDS:
            continue
        if len(tok) < _MIN_TOKEN_LEN:
            continue
        out.append(tok)
    return out


def _tags_as_list(tags: Any) -> list[str]:
    """Accept a JSON string or a list and return a list of tag strings."""
    if tags is None:
        return []
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            return [str(t) for t in parsed] if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(tags, (list, tuple)):
        return [str(t) for t in tags]
    return []


def _item_terms(item: Mapping[str, Any]) -> set[str]:
    """All searchable tokens for an item: description words + tag words."""
    terms = set(_tokenize(item.get("description")))
    for tag in _tags_as_list(item.get("tags")):
        terms.update(_tokenize(tag))
    return terms


def _score_item(
    query_tokens: set[str],
    location_tokens: set[str],
    item: Mapping[str, Any],
) -> tuple[float, list[str]]:
    """Return a score and the list of overlapping words that explain the match."""
    item_terms = _item_terms(item)
    hits = sorted(query_tokens & item_terms)
    score = float(len(hits))

    loc_terms = set(_tokenize(item.get("where_found")))
    loc_hits = sorted(location_tokens & loc_terms)
    score += _LOCATION_WEIGHT * len(loc_hits)

    # Boost when the query names the item's primary type (all type words must match).
    primary_tokens = set(_tokenize(item.get("primary_type")))
    if primary_tokens and primary_tokens <= query_tokens:
        score += _PRIMARY_TYPE_WEIGHT

    return score, hits + [f"location: {w}" for w in loc_hits]


def _reason_text(hits: Sequence[str]) -> str:
    """Build a short, friendly match reason from overlapping terms."""
    if not hits:
        return "related item"
    shown = list(hits)[:5]
    return "matched: " + ", ".join(shown)


def rank(
    query: str,
    location: str | None,
    items: Sequence[Mapping[str, Any]],
) -> list[Match]:
    """Rank items against the query (and optional location), best first.

    Items with no overlap at all are dropped. Ties keep newer items first by relying on
    the caller's input order (db reads sort newest-first), which Python's stable sort
    preserves.
    """
    query_tokens = set(_tokenize(query))
    location_tokens = set(_tokenize(location))

    matches: list[Match] = []
    for item in items:
        score, hits = _score_item(query_tokens, location_tokens, item)
        if score <= 0:
            continue
        matches.append(
            Match(item=dict(item), score=score, reason=_reason_text(hits))
        )

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


def split_sections(
    matches: Sequence[Match], count: int
) -> tuple[list[Match], list[Match]]:
    """Partition ranked matches into (unclaimed-ish, retrieved), each capped at `count`.

    The first section holds `unclaimed` and `pending_pickup` items; the second holds
    `retrieved` items. The cap applies to each section separately.
    """
    active: list[Match] = []
    retrieved: list[Match] = []
    for m in matches:
        if m.status == STATUS_RETRIEVED:
            retrieved.append(m)
        else:
            active.append(m)
    return active[:count], retrieved[:count]
