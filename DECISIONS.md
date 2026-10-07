# Design decisions

Each entry: what we chose, what we rejected, why.

## Pre-signed S3 uploads instead of uploading through Django
- **Chosen:** the client asks the API for a pre-signed POST (PDF content type and size range enforced by S3), uploads directly, then calls `/complete/`. That call verifies the object exists, checks the size and the `%PDF-` magic bytes, and deletes anything that fails.
- **Rejected:** streaming files through Django. It ties up workers on large uploads and puts file bytes in app memory.
- **Trade-off:** there's an extra round trip, and a report sits in `awaiting_upload` until the client calls `/complete/`.

## Out-of-scope reports return 404, not 403
- **Chosen:** visibility is enforced with a queryset filter (`reports_visible_to`), so other users' reports simply don't exist from the caller's point of view.
- **Rejected:** fetching the report and then returning 403. That would confirm which report IDs exist, and those IDs are already random UUIDs.

## Roles: patient vs. center staff, enforced in the database
- A check constraint guarantees that staff always have a center and patients never do.
- Self-registration creates patients only. Staff accounts are created by admins.

## Consent recorded per purpose
- Storing reports and LLM extraction are separate consents. Each records the policy version and a `withdrawn_at` time.
- Upload is blocked without an active storage consent.
- **Next:** LLM extraction will be skipped (manual entry only) for patients without LLM consent.

## Audit log on every access to patient data
- Every create, list, view and download writes an `AccessLog` row.
- Rows are append-only. Nothing in the app updates or deletes them.

## Observations modelled after FHIR Observation, coded with LOINC
- Each value stores what was printed (value and unit) and a canonical version (value and unit), plus the reference range printed on the report.
- The `(patient, loinc, effective_date)` index serves the trend query.

## JWT with short-lived access tokens
- Access tokens last 15 minutes and refresh tokens 1 day.
- Auth endpoints use a tighter rate limit (`auth` throttle scope, 10/min).

## Celery task claims the report under a row lock
- **Chosen:** `select_for_update` moves the report from UPLOADED to PROCESSING. A redelivered or duplicate task finds a different status and does nothing.
- **Rejected:** trusting the broker to deliver exactly once. With `acks_late`, a task can be delivered more than once by design.
- **Retries:** network errors, 429s and 5xx from Claude or S3 retry with exponential backoff (3×). Every other error fails straight away with the reason stored on the report, because retrying a bad PDF won't fix it.

## Only clean rows become observations
- A row with any validation issue (unknown marker, wrong unit, impossible value, duplicate) stays in `Report.extraction` and the report goes to `needs_review`. A report with no collection date stores nothing, since a value without a date can't sit on a timeline.
- **Rejected:** storing everything and flagging it afterwards. A bad value on a trend chart does more harm than a missing one.

## Review replaces the report's values wholesale
- The reviewer submits the full, corrected list. It's validated with the same unit and plausibility rules, then replaces all of the report's observations and marks them verified.
- **Rejected:** patching individual rows. It's harder to audit and easy to leave half-reviewed reports behind.

## Erasure deletes files before database rows
- If S3 fails partway, the account and its rows survive and the request can be retried. The reverse order would leave health data in storage with no owner and no way to find it.
- Audit rows are kept, with the actor set to null.

## Trend reference ranges are generic and marked approximate
- Ranges differ by lab, age and sex. Each point carries its center so the client can show where it came from.
- **Next:** extract the reference range printed on each report and prefer it over the generic one.

## Local S3 runs on moto server, not MinIO
- MinIO's public container images are no longer published on Docker Hub. Moto is already the test double, so local dev and tests use the same S3 behaviour.

## Frontend keeps the access token in memory and the refresh token in sessionStorage
- **Chosen:** the 15-minute access token lives only in a JavaScript variable. The 1-day refresh token is in sessionStorage, so a reload keeps you signed in, but closing the tab ends the session. A 401 triggers one refresh, shared across concurrent requests, then sign-out.
- **Rejected:** localStorage, which keeps tokens across browser restarts and is readable by any XSS for longer. Also rejected: httpOnly refresh cookies, the stronger option, which would need CSRF handling on the refresh endpoint. That's the next step before a real deployment.

## Frontend validates every API response with zod
- The API is external input to the browser. A schema mismatch fails in one place with a clear error, instead of `undefined` showing up deep inside a component.

## Same-origin API in dev and in Docker
- Vite's dev proxy and nginx both serve `/api` from the page's own origin, so Django needs no CORS configuration.
- Only S3 needs CORS, because the browser uploads directly to the pre-signed URL. In Docker, `S3_PUBLIC_ENDPOINT_URL` signs those URLs for a hostname the browser can reach.

## Staff see only their own center's results (audit fix)
- **Problem found:** staff could create a report for any consenting patient by username. Because trends were gated only on "this patient has a report at your center", that one upload gave a center access to the patient's results from every other center.
- **Chosen:** staff trend queries are filtered to observations from reports at the staff member's own center. Uploading on a patient's behalf still works, but it only exposes what that center itself recorded.
- **Next:** an explicit patient-granted care relationship (patient ↔ center), required before staff can upload or read anything. That's the stronger model for a real deployment.

## Refresh tokens rotate and can be revoked (audit fix)
- `ROTATE_REFRESH_TOKENS` and `BLACKLIST_AFTER_ROTATION` are on, and `POST /api/auth/logout/` blacklists the current refresh token. A stolen refresh token stops working the next time the real client refreshes, or immediately on sign-out.
- Refresh has its own rate-limit scope (60/min), separate from sign-in (10/min). A burst of sign-in attempts from one IP can't sign out active users.

## Identifier redaction is defence in depth, not a guarantee
- **Lines dropped:** any line with an identifying label (name, ID numbers, contact details, date of birth, age/sex, referring doctor), an honorific followed by a name, or an age/sex token like `45Y/M`.
- **Values scrubbed on every kept line:** e-mail addresses and runs of 10 or more digits (phones, Aadhaar, MRNs).
- It's still a deny-list, so the LLM call is also gated on explicit consent. The tests pin down both what must be removed and the result rows that must survive.

## Patients may verify values on their own self-uploads
- "Verified" means a human checked the values against the PDF. For a self-uploaded report with LLM extraction off, the patient is the only person who can enter the values.
- Trends show each point's source center, so a reader can tell lab-uploaded values from self-entered ones.
- **Next:** store `verified_by` so clinical views can require staff verification.

## Bounded work per PDF
- PDFs over 20 pages are rejected before parsing. `pdftoppm` renders at most that many pages, and Pillow's decompression-bomb limit is set explicitly (40 MP).
- Together with the subprocess timeout and the Celery time limit, this bounds the CPU, memory and disk a hostile file can use.

## User-facing errors are generic
- `Report.error` holds a fixed, friendly message. Exception details go to the logs only, so internal paths and API responses never reach clients.
