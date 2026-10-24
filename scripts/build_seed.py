"""One-time script to build demo seed data for Whose? from openly-licensed images.

Pipeline:
  1. Search Openverse (https://api.openverse.org) for everyday lost-item categories,
     restricted to CC0 and CC BY licenses (reuse allowed, with attribution).
  2. Download ~20 images, resize each so the longest side is <= 800px, and save them to
     data/seed_images/ with slugged filenames.
  3. Run each image through ai.describe_item once, pausing between calls and retrying on
     429 / rate-limit errors with exponential backoff.
  4. Write data/seed_items.json: per item the image filename, AI description, tags,
     sensitive / high_value flags, a realistic UTD where_found, a pickup location id, and
     an invented hidden detail. The required mix (>=1 sensitive, >=1 high_value, plus
     pending/retrieved roles) is enforced before writing.
  5. Write data/seed_images/CREDITS.md with per-image attribution and the license.

The script is RESUMABLE: images already recorded in seed_items.json are skipped, so an
overloaded model or an interruption does not force a restart. Run it from the project root:

    python scripts/build_seed.py

Requires GEMINI_API_KEY in the environment or .streamlit/secrets.toml, plus `requests`
and `pillow`. This script is a dev tool; it is never imported by the app.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field

# Make the project importable when run as `python scripts/build_seed.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from PIL import Image  # noqa: E402

from whose import ai, config, db  # noqa: E402

# --- paths -----------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEED_IMG_DIR = os.path.join(_ROOT, "data", "seed_images")
_SEED_JSON = os.path.join(_ROOT, "data", "seed_items.json")
_CREDITS = os.path.join(_SEED_IMG_DIR, "CREDITS.md")

# --- Openverse search ------------------------------------------------------
_OPENVERSE = "https://api.openverse.org/v1/images/"
_LICENSES = "cc0,by"  # CC0 (public domain) + CC BY (attribution). Reuse allowed.
_MAX_EDGE = 800
_PER_CATEGORY = 3       # aim ~3 per category * 8 categories ~= up to 24, trimmed to ~20
_TARGET_TOTAL = 20
_AI_PAUSE_SECONDS = 4   # polite pause between AI calls for the free tier
_MAX_RETRIES = 5

# Category -> (search query, realistic UTD where_found, pickup location id).
_CATEGORIES = [
    ("water bottle", "3rd floor study area, McDermott Library", "mcdermott"),
    ("backpack", "Group study table, second floor McDermott Library", "mcdermott"),
    ("headphones", "Charging station, Student Union food court", "student_union"),
    ("keys", "Bike rack outside the Student Union", "student_union"),
    ("umbrella", "Reading area, first floor McDermott Library", "mcdermott"),
    ("jacket", "Locker room, Activity Center", "rec_center"),
    ("laptop", "ECSS second floor hallway outside 2.305", "ecss"),
    ("phone case", "Bus stop shelter at the Comet Cruiser stop", "police"),
]

# Invented hidden details per category (describe something not visible in a stock photo).
_HIDDEN_DETAILS = {
    "water bottle": "A faded UTD Comets sticker is stuck to the bottom.",
    "backpack": "A small panda keychain hangs from the front zipper pull.",
    "headphones": "The owner's initials are written in marker inside the case lid.",
    "keys": "There is a tiny rubber duck charm and a grocery store tag on the ring.",
    "umbrella": "The wrist strap is frayed and repaired with a strip of white tape.",
    "jacket": "A concert ticket stub from last spring is tucked in the left pocket.",
    "laptop": "A robotics club sticker is on the underside near the vents.",
    "phone case": "A folded bus pass is wedged behind the case on the back.",
}


@dataclass
class SeedRecord:
    """One finished seed item, serialized to seed_items.json."""

    image: str
    category: str
    description: str
    tags: list[str] = field(default_factory=list)
    sensitive: bool = False
    high_value: bool = False
    where_found: str = ""
    location_id: str = ""
    hidden_detail: str = ""
    role: str = "unclaimed"  # unclaimed | pending | retrieved (lifecycle hint for seed.py)


@dataclass
class Credit:
    """Attribution metadata for one downloaded image."""

    image: str
    title: str
    creator: str
    source_url: str
    license: str
    license_url: str


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text]
    return "".join(keep).strip("-").replace("--", "-")


def _search_category(query: str, needed: int) -> list[dict]:
    """Return up to `needed` CC0/CC BY image results for a query."""
    params = {
        "q": query,
        "license": _LICENSES,
        "page_size": 20,
        "mature": "false",
    }
    headers = {"User-Agent": "whose-seed-builder/1.0 (hackathon demo)"}
    resp = requests.get(_OPENVERSE, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    picked: list[dict] = []
    for r in results:
        if not r.get("url"):
            continue
        picked.append(r)
        if len(picked) >= needed:
            break
    return picked


def _download_and_resize(url: str, dest_path: str) -> bool:
    """Download an image, resize longest edge to <= _MAX_EDGE, save as JPEG. True on success."""
    try:
        headers = {"User-Agent": "whose-seed-builder/1.0 (hackathon demo)"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        img.thumbnail((_MAX_EDGE, _MAX_EDGE))
        img.save(dest_path, format="JPEG", quality=85)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ! download/resize failed for {url}: {exc}")
        return False


def _describe_with_retry(image_path: str) -> ai.ItemAI | None:
    """Call ai.describe_item with backoff on rate-limit / transient errors."""
    with open(image_path, "rb") as f:
        data = f.read()
    delay = 8
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return ai.describe_item(data, "image/jpeg")
        except ai.AIRateLimitError as exc:
            if attempt == _MAX_RETRIES:
                print(f"  ! giving up after {attempt} rate-limit retries: {exc}")
                return None
            print(f"  … rate limited (attempt {attempt}), waiting {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, 90)
        except ai.AIError as exc:
            print(f"  ! AI error: {exc}")
            return None
    return None


def _load_existing() -> tuple[list[SeedRecord], list[Credit]]:
    """Load any prior run so we can resume without redoing work."""
    records: list[SeedRecord] = []
    if os.path.exists(_SEED_JSON):
        with open(_SEED_JSON, encoding="utf-8") as f:
            for row in json.load(f):
                records.append(SeedRecord(**{k: row[k] for k in row if k in SeedRecord.__annotations__}))
    return records, []


def _enforce_required_mix(records: list[SeedRecord]) -> None:
    """Guarantee >=1 sensitive, >=1 high_value, >=1 pending, >=1 retrieved.

    The AI sets sensitive/high_value from the photo; if the batch happens to lack one,
    nudge suitable categories so the demo always has the full mix. Lifecycle roles
    (pending/retrieved) are assigned here as hints consumed by seed.py.
    """
    if not records:
        return

    # sensitive: ensure at least one. A phone case / laptop photo won't be sensitive,
    # so if none, mark nothing falsely; instead pick the 'keys' or 'phone case' item and
    # leave sensitive honest — but the demo needs one, so flag the phone-case item which
    # can plausibly hide a bus pass / card.
    if not any(r.sensitive for r in records):
        for r in records:
            if r.category in ("phone case", "keys"):
                r.sensitive = True
                r.description = "A personal item found closed; contents withheld."
                break
        else:
            records[0].sensitive = True

    if not any(r.high_value for r in records):
        for r in records:
            if r.category in ("laptop", "headphones"):
                r.high_value = True
                break

    # Lifecycle roles: assign pending + retrieved to two non-sensitive items so the
    # desk/handoff demos have data. Prefer common items.
    assigned_roles = {r.role for r in records}
    if "pending" not in assigned_roles:
        for r in records:
            if r.role == "unclaimed" and not r.sensitive:
                r.role = "pending"
                break
    if "retrieved" not in assigned_roles:
        for r in records:
            if r.role == "unclaimed" and not r.sensitive:
                r.role = "retrieved"
                break


def _write_json(records: list[SeedRecord]) -> None:
    with open(_SEED_JSON, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, indent=2, ensure_ascii=False)


def _write_credits(credits: list[Credit]) -> None:
    lines = [
        "# Seed image credits",
        "",
        "Demo images were sourced from **Openverse** (https://openverse.org), filtered to "
        "**CC0 1.0** and **CC BY 4.0** licenses. CC0 images are public domain; CC BY images "
        "are reused here with attribution as required by their license.",
        "",
        "| Image | Title | Creator | Source | License |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in credits:
        lines.append(
            f"| `{c.image}` | {c.title or '—'} | {c.creator or '—'} | "
            f"[source]({c.source_url}) | [{c.license}]({c.license_url}) |"
        )
    lines.append("")
    with open(_CREDITS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    os.makedirs(_SEED_IMG_DIR, exist_ok=True)
    records, _ = _load_existing()
    done_images = {r.image for r in records}
    credits: list[Credit] = []

    print(f"Resuming with {len(records)} existing records.")

    for query, where_found, location_id in _CATEGORIES:
        if len(records) >= _TARGET_TOTAL:
            break
        print(f"\n== {query} ==")
        try:
            results = _search_category(query, _PER_CATEGORY)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! search failed: {exc}")
            continue

        for i, r in enumerate(results):
            if len(records) >= _TARGET_TOTAL:
                break
            filename = f"{_slug(query)}-{i + 1}.jpg"
            if filename in done_images:
                print(f"  - {filename} already done, skipping")
                continue

            dest = os.path.join(_SEED_IMG_DIR, filename)
            if not _download_and_resize(r["url"], dest):
                continue
            print(f"  saved {filename}")

            credits.append(
                Credit(
                    image=filename,
                    title=r.get("title", ""),
                    creator=r.get("creator", ""),
                    source_url=r.get("foreign_landing_url") or r.get("url", ""),
                    license=f"{str(r.get('license', '')).upper()} {r.get('license_version', '')}".strip(),
                    license_url=r.get("license_url", "") or "https://creativecommons.org/",
                )
            )

            print("  describing with AI...")
            result = _describe_with_retry(dest)
            if result is None:
                # Keep the image + credit, mark for a later resumable pass.
                print("  ! description unavailable; leaving image for a later run")
                os.remove(dest)
                credits.pop()
                continue

            records.append(
                SeedRecord(
                    image=filename,
                    category=query,
                    description=result.description or f"A {query}.",
                    tags=result.tags,
                    sensitive=result.sensitive,
                    high_value=result.high_value,
                    where_found=where_found,
                    location_id=location_id,
                    hidden_detail=_HIDDEN_DETAILS.get(query, "A small private detail."),
                )
            )
            done_images.add(filename)
            _write_json(records)  # persist after each success (resumable)
            time.sleep(_AI_PAUSE_SECONDS)

    _enforce_required_mix(records)
    _write_json(records)
    _write_credits(credits)

    print(
        f"\nDone. {len(records)} items in {_SEED_JSON}. "
        f"Credits written to {_CREDITS}."
    )
    # Quick sanity summary.
    print(
        "  sensitive:", sum(r.sensitive for r in records),
        "| high_value:", sum(r.high_value for r in records),
        "| pending:", sum(r.role == "pending" for r in records),
        "| retrieved:", sum(r.role == "retrieved" for r in records),
    )
    # Validate location ids against config.
    valid = {loc["id"] for loc in config.PICKUP_LOCATIONS}
    bad = [r.image for r in records if r.location_id not in valid]
    if bad:
        print("  ! WARNING: unknown location ids on:", bad)


if __name__ == "__main__":
    main()
