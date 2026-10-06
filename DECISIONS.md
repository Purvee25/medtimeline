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
