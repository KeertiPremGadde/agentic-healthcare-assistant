# Phase 6 (frontend): interview Q&A

What we built: a Next.js chat UI over the streaming API: live agent steps, sources, a booking
confirmation card, safety cards, an appointments page and an "Add to calendar" file. Code:
`frontend/`. Decisions: [ADR 0011](../adr/0011-frontend.md).

---

### Why not `EventSource` or the Vercel AI SDK?
`EventSource` can't POST or send an `Authorization` header. `useChat` speaks the AI SDK's own
stream protocol, and our events (`step`, `confirmation`, `done{pending}`) don't map onto it, so an
adapter would hide the interesting parts. So `fetch` plus a response-body reader: about 60 lines,
unit-tested, and I can explain every line.

### What is hard about parsing SSE?
Network chunks don't respect event boundaries: an event can arrive in two pieces, two events in
one, and the split can land mid-line or between `\r` and `\n`. The parser buffers text until a
blank line, ignores `:` comment lines (our keepalives) and joins multiple `data:` lines. Tests
feed it split chunks, CRLF, keepalives and non-ASCII text.

### How does the human-in-the-loop confirmation look in the UI?
The graph pauses (`interrupt`), the stream ends with a `confirmation` event and `done{pending:true}`.
The UI shows a card and disables the composer; Confirm or Change time call `POST /resume`, which
continues the same conversation and costs no model call. After a page refresh the pending
confirmation is restored from `GET /v1/chat/{id}`, because the state lives in the checkpointer, not
in the browser.

### How does the UI know a reply is an emergency or a booking?
The server tells it: the `message` event carries `kind`. I deliberately did not detect it by
looking at the text in the browser: the rules that decide are server-side and deterministic, and a
client that guesses can disagree with them. Crisis (harmful intent) gets a calm card, not a red
alarm, because a person in distress is not helped by a warning screen.

### Where do you keep the JWT, and why?
In memory plus `sessionStorage`. An httpOnly cookie resists XSS better, but needs cookie auth,
CSRF protection and credentialed CORS across two sites. The token is short lived and holds no
personal data, accounts are username-only and the UI renders no untrusted HTML. It's a documented
trade-off that I'd revisit if accounts held real data.

### What bug did the tests catch?
Next.js 16 keeps the state of pages you navigate away from. After logout and login as someone else
in the same tab, the previous user's chat and a stuck "Please wait…" login button were still in
memory. A saved conversation id in `sessionStorage` had the same problem. The fix is
`UserScope` (remount on token change) plus clearing the id on login and logout, with a Playwright
test that failed before the fix. The API would have answered 404 for the other user's conversation,
but data should not be in the browser at all.

### How is the `.ics` file built, and what's in it?
RFC 5545 text: `BEGIN:VCALENDAR`, one `VEVENT`, CRLF line endings, text escaping (`,` `;` `\`
newlines), lines folded at 75 octets without splitting a multi-byte character, times in UTC so no
timezone block is needed, and a stable `UID` so importing twice updates the event. It says "Appointment
with Dr. X" and the time. No patient data and no attendee: the clinic's shared calendar can't invite
people (a service account can't), so this is the patient-side counterpart.

### How do the doctor cards work without parsing text?
The `message` event carries the options as data (`doctors`), in the same order the assistant numbers
them. The Book button sends "Book number N", exactly what a user would type, so the booking flow,
including the mandatory confirmation, is unchanged. The options are attached only to the turn that
suggested them (the graph remembers them, but a later turn must not re-send them), and older cards
are disabled because "number N" always means the newest list.

### What did you do for the safety cards?
Made them actionable without changing what the server says: `tel:` links on the emergency card and a
"Call 112" button; on the crisis card plain text, call buttons for TelefonSeelsorge and 112, and a
Giftnotruf section (each number appears once as an action). Germany has no single poison-control
number, so I show only the two I read on the official BfR directory (Berlin, München), link that
directory for every other region, and left out numbers I'd only seen on third-party lists. The source
and the date I checked are in the code next to the numbers.

### What did the real-stack check find that the mock didn't?
That replacing text with a card can drop information: the confirmation question can start with a
reason ("Dr. X doesn't work on Sundays"), and a card showing only doctor and time would have offered a
different day with no explanation. The card now shows that reason. A mock only returns what I thought
to put in it, so I run the real stack once before every PR.

### How do you test a streaming UI for free?
A tiny Node server speaks the real contract (CORS, SSE with delays, error envelopes, per-user
state). Playwright drives the real frontend against it: register, ask, see the live step line, book,
confirm, download the `.ics`, cancel, hit the demo limit. No API key, no cost, deterministic. It's
a test double, so I also ran the real stack once by hand (Haiku, MCP tools, Google Calendar).

### What about accessibility?
Labels on every input, a skip link, focus rings, `role=log` with `aria-busy`, `role=status` for the
step line, `role=alert` for emergencies, reduced-motion support, large touch targets, light and dark
themes (I chose the palette for readable contrast but have not audited it with a tool), and colour
never being the only signal (every card has an icon and a title).

### What would you do next?
Real token streaming, refresh tokens and account deletion, a cookie-based session when the frontend
and API share a site, and an i18n layer (the backend already answers in German).
