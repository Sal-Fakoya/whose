# Structure

```
app.py                 # entry point: page config, init db, seed, route by session_state["view"]
whose/
  __init__.py
  config.py            # pickup locations (name, building, phone, email, hours), constants
  db.py                # sqlite connection, schema, CRUD functions
  ai.py                # the only module that talks to Gemini
  matching.py          # rank items against a lost-item description, split by status
  verify.py            # hidden-detail check, attempt limits, status changes
  seed.py              # demo items, inserted on startup if the db is empty
  views/
    home.py            # "I found something" / "I lost something" / desk link
    found.py           # post a found item
    lost.py            # search with 5/10/15 selector, two ranked result sections
    item.py            # item detail, verification, pickup instructions
    desk.py            # passcode-protected desk view: pending list, mark retrieved, archive
    handoff.py         # finder enters handoff code to mark retrieved
data/
  images/              # uploaded images (gitignored)
  seed_images/         # optional images for demo items (committed)
tests/
  test_verify.py
  test_matching.py
.streamlit/
  config.toml
requirements.txt
README.md
```
