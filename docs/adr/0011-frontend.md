# 0011 – Frontend: Next.js, a custom stream reader and token storage

Status: accepted (Phase 6)

## Context
The API (ADR 0008) streams Server-Sent Events with custom event types (`step`, `token`,
`confirmation`, `message`, `done`, `error`) and pauses for a yes/no through a resume endpoint. The
frontend has to show the live agent steps, sources, a confirmation card, safety replies and an
"Add to calendar" file, on phones as well as desktops, and it must never mix up two users on one
browser.

## Decisions

### 1. Next.js (App Router) + TypeScript strict + Tailwind + shadcn/ui, Node 22 LTS
The app is a client-side UI over a separate API, so it uses client components and no server
actions. Node is pinned with `.nvmrc` and `engines` (CI uses the same file). shadcn/ui gives
accessible primitives that we own as source files; the class helper is `clsx` + `tailwind-merge`
(the shadcn init had added an unrelated npm package named `cn`; it was replaced).

### 2. A small `fetch` stream reader, not the Vercel AI SDK `useChat`
`useChat` expects its own stream protocol. Our events (`step`, `confirmation`, `done{pending}`)
have no equivalent there, so an adapter would hide exactly the parts worth showing. `EventSource`
is out too: it can't send an `Authorization` header or POST. `lib/sse.ts` is an incremental parser
(buffers partial events, handles CRLF, ignores keepalive comments) and `lib/use-chat.ts` is the
state machine. Both are unit-tested.

### 3. The server says how to present a reply (`kind`), the client never parses text to decide
The `message` event (and `ChatResponse`) now carries `kind` (`normal` | `booked` | `emergency` |
`harmful_intent`) and, for a booking, `appointment_id`. This is additive: old clients ignore it.
Emergency replies get a red alert card; harmful-intent replies get a calm violet "you are not
alone" card (a crisis is not an alarm); a booking gets a success card with the calendar button.
Red is used for nothing else. The only text parsing is cosmetic: splitting the `Sources:` block and
the disclaimer from an answer to lay them out (`lib/citations.ts`); the disclaimer itself is still
added server-side in code.

### 3b. Structured data for cards: `doctors` and `booking`
The same event carries the doctor options of the turn that suggested them (`doctors`: id, name,
specialty, city, languages, in the order the assistant numbers them) and, after a booking,
`booking` (appointment id, doctor, time as shown in the clinic's timezone). The doctor list is
conversation memory in the graph, so it is attached only to the turn that suggested it
(`draft_kind == "doctors"`), which a test pins. A Book button sends "Book number N", the exact
sentence a user would type, so the booking flow is unchanged and the confirmation step is still
mandatory. A Book tap on its own makes the assistant ask for a day, as typing "Book number 1"
would. Cards of older lists are disabled because "number N" refers to the newest list, and disabled
buttons say why ("Answer the confirmation below first."). The reply reads as intro, cards, a
hint, then the not-a-diagnosis note: the list is found by exact match on the known doctor names
(`lib/doctor-reply.ts`), the numbered lines, the generic label and the text hint are dropped, and
if the list isn't recognised the text is shown unchanged. Likewise the confirmation card shows the
explanation the assistant gives before asking (for example "Dr. X doesn't work on Sundays"),
because the card shows the doctor and time as data and would otherwise offer a different day with
no reason.

### 3c. Safety actions are one tap away
The emergency and crisis texts are fixed on the server; the UI only makes them actionable. On the
emergency card every known number in the text is a `tel:` link (a fixed list, not a regex over
arbitrary digits) and there is a "Call 112" button. The crisis card keeps its text plain and carries
the numbers on buttons (TelefonSeelsorge, 112), so each number appears once as an action, plus a
Giftnotruf (poison control) section. Germany has no single poison-control number, so that section
shows only numbers confirmed on the official directory of the Federal Institute for Risk Assessment
(BfR, "Giftinformationszentren in Deutschland", marked "Stand: 22.07.2026", read on 2026-11-01):
Berlin 030 19240 and München 089 19240. Every other region is sent to the directory, and 112 is the
answer for an emergency. Numbers seen only on third-party lists were deliberately left out. The
source and date are recorded next to the numbers in `safety-cards.tsx`.

### 4. Token storage: memory plus `sessionStorage`, not an httpOnly cookie
A cookie is the safer place against XSS, but it would need cookie auth on the API, CSRF
protection, `SameSite` handling and credentialed CORS, and the Vercel frontend and the AWS API
will be on different sites (Phase 8). Here the token lives in memory and `sessionStorage` (a
refresh keeps you logged in, closing the tab logs you out), it is short lived (60 min), holds no
personal data, accounts are username-only, and the UI renders no untrusted HTML (React escapes
text; the only links are `http(s)` sources from our own corpus, with `rel="noopener noreferrer"`).
Accepted trade-off; revisit if accounts ever hold real data. Closes the open point of ADR 0008.

### 5. One user per tab, enforced
Next.js 16 keeps the state of routes you navigated away from. `UserScope` remounts the whole page
tree when the token changes, and the saved conversation id is cleared on every login and logout.
Without both, the next person to log in on a shared browser could see the previous chat. A
Playwright test covers it (it failed before the fix).

### 6. `.ics` built in the browser
The file is generated client-side from the appointment record (`GET /v1/appointments` has the
doctor and the UTC start), so no API change is needed. RFC 5545: CRLF, text escaping, 75-octet
line folding (without splitting a character), UTC times, a stable `UID` per appointment so a
re-import updates instead of duplicating. The event names the doctor and the time only: no
patient data, no attendee. This is the patient-side counterpart of the shared demo calendar (a
service account cannot invite attendees, ADR 0007).

### 7. Tests without cost or flakiness: a mock API that speaks the real contract
Playwright runs the real frontend against `tests/e2e/mock-api.mjs`, a small Node server with real
CORS, real streaming with delays (so the live step line can be asserted), error envelopes and
per-user conversations. It makes no model calls. It is a test double: the real stack was also
driven once by hand (see the PR). Unit tests (Vitest) cover the SSE parser, event decoding, the
citation parser and the `.ics` builder.

### 8. Accessibility and look
Labelled controls, a skip link, visible focus rings, `role=log` with `aria-busy` for the
conversation, `role=status` for the step line, `role=alert` for emergency and limit notices,
44 px touch targets in the composer, reduced-motion support, light and dark themes (system
default, toggle stored per browser). Colours carry meaning: blue = action, amber = disclaimer, red
= emergency, green = success, violet = crisis support.

## Consequences
- The API contract gained `kind` / `appointment_id`; the demo page and tests are unaffected.
- The frontend needs `API_CORS_ORIGINS` to include its origin (default `http://localhost:3000`) and
  `NEXT_PUBLIC_API_URL` at build time.
- Streaming tokens remain a replay of the finished answer (ADR 0008); the step line is live.
- Not built: refresh tokens, account deletion, token-by-token streaming, i18n.
