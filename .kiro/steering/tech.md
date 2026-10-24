# Tech

- Language: Python 3.11
- UI: Streamlit (single app, no other web frameworks)
- Database: SQLite via the standard library sqlite3 module, file at data/whose.db
- Images: saved to data/images/ with uuid filenames
- AI provider: Google Gemini API, a Flash model with image input, via the official google-genai SDK. All model calls go through whose/ai.py.
- Secrets: GEMINI_API_KEY and DESK_PASSCODE come from st.secrets or environment variables. Never hardcode them. .streamlit/secrets.toml and .env must be in .gitignore.
- Deployment: Streamlit Community Cloud. Local files there are not permanent, so seed data must reload automatically when the database is empty.
- Dependencies: pinned in requirements.txt. Do not add a dependency without a clear need.

## Streamlit rerun rules (important)
Streamlit reruns the whole script on every interaction. Follow these rules everywhere:
- Call the AI only inside a form submit handler. Never call the AI at the top level of a page or on widget change.
- Store AI results in the database immediately and read them from there afterward.
- Use st.form for every input screen (post item, search, verify, desk actions, handoff code).
- Keep navigation and UI state (current view, selected item id, search text, result count, search results) in st.session_state.
- Create the AI client once with st.cache_resource.
- Use st.fragment only if a section is still visibly jumpy.

## AI error handling
- Wrap every AI call. On failure, show a friendly message and never crash the page.
- On HTTP 429 / RESOURCE_EXHAUSTED, tell the user to try again in a minute.
- A failed AI call during verification never counts as a used attempt.

## Code style
- Small functions with type hints and short docstrings.
- Business logic lives in whose/ modules, not in view files, so it can be tested without Streamlit.
- Contact details for pickup locations are obvious placeholders (for example 972-555-0100, desk@example.edu), never invented real-looking ones.

## UI conventions
- The UI never uses emojis. This covers the page title, page icon, buttons, headings, captions, and status messages. Use plain text labels, or Streamlit's built-in Material icons (for example icon=":material/search:") where an icon genuinely helps. Typographic punctuation such as the em dash and middle dot is fine; it is not an emoji.
- Accent colors are UT Dallas orange (primaryColor in .streamlit/config.toml) and UT Dallas green (minimal CSS). Do not add a dependency for styling.
- Keep allowed claimant email domains in whose/config.py, not hardcoded in views. DEMO_MODE (from st.secrets or env, default false) only widens the accepted domains to include @gmail.com and toggles the demo notices.
