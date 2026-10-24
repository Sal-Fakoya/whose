"""Health check for the Gemini connection.

Reads GEMINI_API_KEY from .streamlit/secrets.toml or the environment, makes one live call
through whose.ai, and reports the result:

  - Prints "Gemini OK" and exits 0 when the model responds.
  - Prints the error type (and a short reason) and exits 1 when it fails.

This is a dev/ops tool. It is never imported by the app, and it makes exactly one AI call.
Run from the project root:  python scripts/check_gemini.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_secrets_into_env() -> None:
    """Populate env from .streamlit/secrets.toml if present (does not overwrite env)."""
    path = os.path.join(".streamlit", "secrets.toml")
    try:
        import tomllib

        with open(path, "rb") as f:
            for key, value in tomllib.load(f).items():
                os.environ.setdefault(key, str(value))
    except FileNotFoundError:
        pass
    except Exception:
        # A malformed secrets file should not mask the real connection check.
        pass


def main() -> int:
    _load_secrets_into_env()
    from whose import ai

    status = ai.api_key_status()
    if status == "missing":
        print("GEMINI CHECK FAILED: key missing (set GEMINI_API_KEY in secrets or env)")
        return 1

    try:
        # One real call that exercises the same path verification uses.
        ai.judge_answer("There is a label on the back.", "it has a label on the back")
    except ai.AIConfigError as exc:
        print(f"GEMINI CHECK FAILED: AIConfigError -> {str(exc)[:160]}")
        return 1
    except ai.AIRateLimitError as exc:
        print(f"GEMINI CHECK FAILED: AIRateLimitError -> {str(exc)[:160]}")
        return 1
    except ai.AIError as exc:
        print(f"GEMINI CHECK FAILED: AIError -> {str(exc)[:160]}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"GEMINI CHECK FAILED: {type(exc).__name__} -> {str(exc)[:160]}")
        return 1

    print("Gemini OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
