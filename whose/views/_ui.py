"""Shared view helpers: resilient image rendering and path resolution.

Keeps image display from crashing a page when a file is missing or unreadable (design
error-handling rule: degrade gracefully with a placeholder, never crash the view).
"""

from __future__ import annotations

import os

import streamlit as st

# Project root, resolved from this file's location (.../whose/views/_ui.py).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def abs_image_path(relative_path: str) -> str:
    """Resolve a stored relative image path (e.g. data/images/x.jpg) to an absolute path."""
    return os.path.join(PROJECT_ROOT, relative_path)


def safe_image(relative_path: str | None, *, width: int | None = None) -> bool:
    """Render an image if possible; otherwise show a placeholder. Returns True if shown.

    Never raises: a missing file or an unreadable/corrupt image degrades to a caption.
    """
    if not relative_path:
        st.markdown("*No photo available.*")
        return False
    path = abs_image_path(relative_path)
    if not os.path.exists(path):
        st.markdown("*No photo available.*")
        return False
    try:
        st.image(path, width=width)
        return True
    except Exception:
        st.markdown("*Photo could not be displayed.*")
        return False
