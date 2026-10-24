# Product: Whose?

Whose? is a peer-to-peer lost-and-found app for UT Dallas students. Any student who finds an item posts a photo and says who is holding it now. AI describes and tags the item. A student who lost something describes it in plain words and gets ranked matches, along with who to contact about each one. To start a claim, the owner answers a hidden detail the finder recorded that is not visible in the photo. Passing that check does not hand over the item: the owner picks it up in person, and the holder checks their documents before marking it retrieved.

## Problem
Lost items on campus end up scattered across building front desks and group chats. There is no single place to search, students don't know who to contact about an item, and posting a photo publicly lets anyone claim something that isn't theirs.

## Users
- Finders: students who picked up an item and want to return it.
- Owners: students who lost an item and want to find it quickly.
- Lost and Found desk staff: people at campus desks who hold items and confirm pickups.

## Item lifecycle
unclaimed -> pending_pickup -> retrieved
- unclaimed: posted, nobody has passed verification yet.
- pending_pickup: at least one person passed the hidden-detail check and was told where to go and what to bring. Still visible and claimable, because the in-person check decides.
- retrieved: the holder confirmed the in-person handoff (desk staff in the desk view, or the finder with their handoff code).

## Product principles
- The hidden detail is never shown to anyone and never included in public descriptions or ranking data.
- Passing verification earns the right to pick up the item, not ownership. Pickup always requires a student ID, plus proof of purchase or a serial number for high-value items.
- Sensitive items (IDs, payment cards, wallets, phones showing a lock screen, documents) are listed with a generic description and no photo until the claimant passes verification.
- Desk contact details are public. A finder's personal contact appears only after verification.
- Verification attempts are limited to prevent guessing.
- Hackathon build: one core loop, done well.

## Out of scope for this build
Real UTD login, notifications, in-app messaging, maps, automatic semester-end deletion (future work: retrieved items are removed at the end of each semester).
