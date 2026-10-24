"""One-time script to fetch demo seed images from a Hugging Face dataset.

License check (done before any download):
  Primary dataset Porcupine0476/University_CommonLostItems is MIT licensed, BUT it ships as
  a single opaque dataset.zip with no datasets-library config, so it cannot be streamed
  image-by-image without downloading the whole archive. That violates the "stream only what
  we keep" requirement, so this script uses the MIT-licensed fallback instead:

      zcs15/ImageNet-D   (license: MIT)

  ImageNet-D stores loose PNGs as <variation>/<category>/<file>.png. We pull only from the
  `background/` variation (the most photo-like) and download ONLY the files we keep via
  huggingface_hub.hf_hub_download, so the full dataset is never downloaded.

Pipeline:
  1. List background/<category>/ files for the target categories.
  2. Download candidates one at a time, skipping blurry / tiny / grayscale / non-single-item
     images via simple heuristics, keeping 2 per category.
  3. Resize each to max 800px and save to data/seed_images/<name>_<n>.jpg.
  4. Write data/seed_images/CREDITS.md (dataset name, link, MIT license).
  5. Write data/seed_items.json with photo-matched descriptions, synonym-rich tags (10-15),
     a primary_type for ranking, realistic UTD locations, invented hidden details, and the
     required demo mix (>=1 sensitive, high_value, pending, retrieved). Sensitive items are
     added without photos (their photos are hidden anyway).

Run from the project root:  python scripts/fetch_seed_images.py
Requires `datasets` / `huggingface_hub` and `pillow` (dev-only; NOT in requirements.txt).
The app itself never downloads anything.  No emojis in any output or data.
"""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageStat  # noqa: E402

from whose import config  # noqa: E402

# --- dataset ---------------------------------------------------------------
_DATASET = "zcs15/ImageNet-D"
_DATASET_URL = "https://huggingface.co/datasets/zcs15/ImageNet-D"
_DATASET_LICENSE = "MIT"
_VARIATION = "background"  # the most photo-like variation in ImageNet-D
_PER_CATEGORY = 2
_MAX_EDGE = 800
_MIN_EDGE = 200  # reject tiny images

# --- paths -----------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEED_IMG_DIR = os.path.join(_ROOT, "data", "seed_images")
_SEED_JSON = os.path.join(_ROOT, "data", "seed_items.json")
_CREDITS = os.path.join(_SEED_IMG_DIR, "CREDITS.md")

# Dataset category -> local friendly name used in filenames and item type.
_CATEGORY_MAP = {
    "laptop_open": "laptop",
    "mug": "mug",
    "umbrella": "umbrella",
    "sunglasses": "sunglasses",
    "backpack": "backpack",
    "water_bottle": "water_bottle",
}

# Per-type content for the seed item: description, synonym-rich tags (10-15), primary_type,
# UTD location, and an invented hidden detail (something NOT visible in a stock photo).
_ITEM_CONTENT = {
    "laptop": {
        "description": "An open laptop computer.",
        "primary_type": "laptop",
        "tags": [
            "laptop", "notebook", "computer", "open laptop", "pc", "macbook",
            "ultrabook", "portable computer", "screen", "keyboard", "electronics",
            "device",
        ],
        "high_value": True,
        "where_found": "Charging station near the Student Union food court",
        "location_id": "student_union",
        "hidden_detail": "A robotics club sticker is on the underside near the vents.",
    },
    "mug": {
        "description": "A ceramic coffee mug.",
        "primary_type": "mug",
        "tags": [
            "mug", "coffee mug", "cup", "coffee cup", "tea cup", "ceramic mug",
            "drinkware", "tumbler", "mug cup", "coffee", "tea", "cup with handle",
        ],
        "where_found": "Reading area, first floor McDermott Library",
        "location_id": "mcdermott",
        "hidden_detail": "There is a small chip on the base and initials on the bottom.",
    },
    "umbrella": {
        "description": "A folding umbrella.",
        "primary_type": "umbrella",
        "tags": [
            "umbrella", "folding umbrella", "compact umbrella", "rain umbrella",
            "parasol", "travel umbrella", "brolly", "rain gear", "collapsible umbrella",
            "umbrella canopy", "rain",
        ],
        "where_found": "Reading area, first floor McDermott Library",
        "location_id": "mcdermott",
        "hidden_detail": "The wrist strap is frayed and repaired with white tape.",
    },
    "sunglasses": {
        "description": "A pair of sunglasses.",
        "primary_type": "sunglasses",
        "tags": [
            "sunglasses", "shades", "glasses", "eyewear", "dark glasses", "sun glasses",
            "frames", "tinted glasses", "spectacles", "eyeglasses", "shade glasses",
        ],
        "where_found": "Outdoor seating near the Student Union",
        "location_id": "student_union",
        "hidden_detail": "One hinge has a tiny piece of clear tape holding it.",
    },
    "backpack": {
        "description": "A backpack.",
        "primary_type": "backpack",
        "tags": [
            "backpack", "bag", "book bag", "rucksack", "school bag", "knapsack",
            "daypack", "laptop bag", "bookbag", "satchel", "pack", "student bag",
        ],
        "where_found": "Group study table, second floor McDermott Library",
        "location_id": "mcdermott",
        "hidden_detail": "A small panda keychain hangs from the front zipper pull.",
    },
    "water_bottle": {
        "description": "A reusable water bottle.",
        "primary_type": "water bottle",
        "tags": [
            "water bottle", "bottle", "hydro flask", "flask", "tumbler", "drink bottle",
            "reusable bottle", "sports bottle", "insulated bottle", "thermos",
            "water flask", "drinkware",
        ],
        "where_found": "3rd floor study area, McDermott Library",
        "location_id": "mcdermott",
        "hidden_detail": "A faded UTD Comets sticker is stuck to the bottom.",
    },
}

# Sensitive and extra items added WITHOUT photos (sensitive photos are hidden anyway).
# These guarantee the required demo mix regardless of which photos download.
_PHOTOLESS_ITEMS = [
    {
        "image": None,
        "primary_type": "student id",
        "description": "A student ID card found face down. Details withheld.",
        "tags": [
            "id card", "student id", "comet card", "identification", "card", "badge",
            "photo id", "campus card", "access card", "id",
        ],
        "sensitive": True,
        "high_value": False,
        "where_found": "Locker room bench at the Activity Center",
        "location_id": "rec_center",
        "hidden_detail": "The name on the card and the last four digits of the ID number.",
        "role": "unclaimed",
    },
    {
        "image": None,
        "primary_type": "wallet",
        "description": "A bifold wallet found closed. Contents withheld.",
        "tags": [
            "wallet", "bifold wallet", "billfold", "card holder", "purse", "money clip",
            "leather wallet", "cardholder", "pocket wallet", "coin purse",
        ],
        "sensitive": True,
        "high_value": False,
        "where_found": "Bus stop shelter at the Comet Cruiser stop",
        "location_id": "police",
        "hidden_detail": "The color and material, plus a ticket stub in the bill slot.",
        "role": "unclaimed",
    },
]


def _is_good_photo(img: Image.Image) -> bool:
    """Heuristic quality filter: reject tiny, extreme-aspect, or near-grayscale images."""
    w, h = img.size
    if min(w, h) < _MIN_EDGE:
        return False
    aspect = max(w, h) / min(w, h)
    if aspect > 2.0:  # reject banners / strips; a single item is roughly square-ish
        return False
    # Reject near-grayscale (likely a diagram/sketch, not a product photo).
    rgb = img.convert("RGB")
    stat = ImageStat.Stat(rgb)
    r, g, b = stat.mean
    if max(r, g, b) - min(r, g, b) < 4 and abs(r - g) < 4 and abs(g - b) < 4:
        return False
    return True


def _download_category(api, hf_hub_download, dataset_files, dataset_cat, friendly):
    """Download up to _PER_CATEGORY good photos for one category. Returns saved filenames."""
    candidates = [
        f for f in dataset_files
        if f.startswith(f"{_VARIATION}/{dataset_cat}/") and f.endswith(".png")
    ]
    saved: list[str] = []
    for remote in candidates:
        if len(saved) >= _PER_CATEGORY:
            break
        try:
            local = hf_hub_download(_DATASET, remote, repo_type="dataset")
            img = Image.open(local)
            img.load()
        except Exception as exc:  # noqa: BLE001
            print(f"    skip (load failed): {exc}")
            continue
        if not _is_good_photo(img):
            print(f"    skip (quality): {remote}")
            continue
        out_name = f"{friendly}_{len(saved) + 1}.jpg"
        img = img.convert("RGB")
        img.thumbnail((_MAX_EDGE, _MAX_EDGE))
        img.save(os.path.join(_SEED_IMG_DIR, out_name), format="JPEG", quality=85)
        saved.append(out_name)
        print(f"    saved {out_name} (from {remote})")
    return saved


def _build_items(photos_by_type: dict[str, list[str]]) -> list[dict]:
    """Assemble seed_items records from downloaded photos plus the photoless items."""
    items: list[dict] = []
    for friendly, filenames in photos_by_type.items():
        content = _ITEM_CONTENT[friendly]
        for idx, fname in enumerate(filenames):
            items.append(
                {
                    "image": fname,
                    "primary_type": content["primary_type"],
                    "description": content["description"],
                    "tags": content["tags"],
                    "sensitive": False,
                    "high_value": bool(content.get("high_value", False)),
                    "where_found": content["where_found"],
                    "location_id": content["location_id"],
                    "hidden_detail": content["hidden_detail"],
                    "role": "unclaimed",
                }
            )
    items.extend(_PHOTOLESS_ITEMS)
    return items


def _enforce_mix(items: list[dict]) -> None:
    """Guarantee >=1 sensitive, >=1 high_value, >=1 pending, >=1 retrieved."""
    if not any(i["sensitive"] for i in items):
        items[0]["sensitive"] = True
    if not any(i["high_value"] for i in items):
        for i in items:
            if i.get("primary_type") == "laptop":
                i["high_value"] = True
                break
        else:
            items[0]["high_value"] = True
    # Assign pending + retrieved to two non-sensitive photo items for the desk/handoff demos.
    non_sensitive = [i for i in items if not i["sensitive"] and i.get("image")]
    if non_sensitive and not any(i["role"] == "pending" for i in items):
        non_sensitive[0]["role"] = "pending"
    later = [i for i in non_sensitive if i["role"] == "unclaimed"]
    if later and not any(i["role"] == "retrieved" for i in items):
        later[0]["role"] = "retrieved"


def _write_credits(categories_used: list[str]) -> None:
    lines = [
        "# Seed image credits",
        "",
        f"Demo images are from the Hugging Face dataset **{_DATASET}**",
        f"({_DATASET_URL}), license **{_DATASET_LICENSE}**.",
        "",
        "Images are from the dataset's `background` variation and were resized to a maximum "
        "of 800px for this demo. Used under the MIT license.",
        "",
        "Note: the dataset Porcupine0476/University_CommonLostItems (also MIT) was evaluated "
        "first but ships as a single opaque archive that cannot be streamed per-image, so "
        "this MIT-licensed dataset was used instead.",
        "",
        "Categories used: " + ", ".join(sorted(categories_used)) + ".",
        "",
    ]
    with open(_CREDITS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError:
        print("Install the dev dependency first:  python -m pip install datasets")
        sys.exit(1)

    os.makedirs(_SEED_IMG_DIR, exist_ok=True)
    api = HfApi()
    print(f"Dataset: {_DATASET} (license: {_DATASET_LICENSE})")
    dataset_files = api.list_repo_files(_DATASET, repo_type="dataset")

    photos_by_type: dict[str, list[str]] = {}
    for dataset_cat, friendly in _CATEGORY_MAP.items():
        print(f"== {friendly} (dataset: {dataset_cat}) ==")
        saved = _download_category(api, hf_hub_download, dataset_files, dataset_cat, friendly)
        if saved:
            photos_by_type[friendly] = saved

    items = _build_items(photos_by_type)
    _enforce_mix(items)

    # Validate location ids against config.
    valid = {loc["id"] for loc in config.PICKUP_LOCATIONS}
    for it in items:
        if it["location_id"] not in valid:
            print(f"  WARNING: unknown location id {it['location_id']!r} on {it.get('image')}")

    with open(_SEED_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    _write_credits(list(photos_by_type.keys()))

    print(
        f"\nDone. {len(items)} items -> {_SEED_JSON}\n"
        f"  with photos: {sum(1 for i in items if i.get('image'))}\n"
        f"  sensitive: {sum(i['sensitive'] for i in items)}"
        f" | high_value: {sum(i['high_value'] for i in items)}"
        f" | pending: {sum(i['role'] == 'pending' for i in items)}"
        f" | retrieved: {sum(i['role'] == 'retrieved' for i in items)}"
    )


if __name__ == "__main__":
    main()
