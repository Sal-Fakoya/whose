"""Tests for whose.matching ranking and sectioning. No Streamlit, no DB required."""

from __future__ import annotations

from whose import db, matching
from whose.matching import Match


def make_item(
    item_id: int,
    description: str,
    tags: list[str] | None = None,
    status: str = db.STATUS_UNCLAIMED,
    where_found: str = "",
) -> dict:
    """Build a minimal public-item mapping for ranking."""
    return {
        "id": item_id,
        "status": status,
        "description": description,
        "tags": tags or [],
        "where_found": where_found,
    }


def test_rank_orders_by_overlap_and_drops_non_matches():
    items = [
        make_item(1, "black hydro flask water bottle", ["flask", "tumbler"]),
        make_item(2, "red umbrella"),
        make_item(3, "blue water bottle", ["bottle"]),
    ]
    results = matching.rank("lost my black water bottle", None, items)
    ids = [m.item["id"] for m in results]
    # Item 1 shares the most terms (black, water, bottle); item 3 shares (water, bottle).
    assert ids[0] == 1
    assert 3 in ids
    # The red umbrella shares nothing and is dropped.
    assert 2 not in ids


def test_reason_text_lists_matched_terms():
    items = [make_item(1, "black hydro flask", ["flask", "water bottle"])]
    results = matching.rank("black flask", None, items)
    assert results[0].reason.startswith("matched:")
    assert "black" in results[0].reason
    assert "flask" in results[0].reason


def test_location_boost_breaks_ties_toward_location_match():
    # Two items with identical description overlap; one also matches the location.
    items = [
        make_item(1, "silver laptop", where_found="parking garage"),
        make_item(2, "silver laptop", where_found="mcdermott library"),
    ]
    results = matching.rank("silver laptop", "library", items)
    assert results[0].item["id"] == 2
    assert results[0].score > results[1].score


def test_tags_accept_json_string():
    # db rows carry tags as a JSON string; ranking must handle that.
    item = make_item(1, "bottle")
    item["tags"] = '["hydro flask", "tumbler"]'
    results = matching.rank("tumbler", None, [item])
    assert len(results) == 1
    assert "tumbler" in results[0].reason


def test_split_sections_partitions_by_status():
    matches = [
        Match(make_item(1, "a", status=db.STATUS_UNCLAIMED), 3.0, "r"),
        Match(make_item(2, "b", status=db.STATUS_PENDING), 2.0, "r"),
        Match(make_item(3, "c", status=db.STATUS_RETRIEVED), 1.0, "r"),
    ]
    active, retrieved = matching.split_sections(matches, count=10)
    assert [m.item["id"] for m in active] == [1, 2]
    assert [m.item["id"] for m in retrieved] == [3]


def test_split_sections_caps_each_section_separately():
    active_matches = [
        Match(make_item(i, "x", status=db.STATUS_UNCLAIMED), float(100 - i), "r")
        for i in range(8)
    ]
    retrieved_matches = [
        Match(make_item(100 + i, "x", status=db.STATUS_RETRIEVED), float(50 - i), "r")
        for i in range(8)
    ]
    for count in (5, 10, 15):
        active, retrieved = matching.split_sections(
            active_matches + retrieved_matches, count=count
        )
        assert len(active) == min(count, 8)
        assert len(retrieved) == min(count, 8)


def test_archived_exclusion_is_a_db_read_contract():
    # matching never sees archived items because the db read (list_items_for_search)
    # filters archived=0. This asserts the contract via the SQL used there.
    import inspect

    src = inspect.getsource(db.list_items_for_search)
    assert "archived = 0" in src
