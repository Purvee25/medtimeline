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
