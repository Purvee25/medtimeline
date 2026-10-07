# Security policy

## Supported versions

Only the `main` branch is supported. There are no tagged releases.

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through GitHub:
**Security** tab, then **Report a vulnerability**
([private vulnerability reporting](https://github.com/Purvee25/medtimeline/security/advisories/new)).

Include steps to reproduce, the affected endpoint or file, and the impact. You should get a response within a few days.

## Scope

- MedTimeline is a portfolio project, not a medical device, and is not deployed with real users.
- All data in this repository is **synthetic**. Real PHI must never be uploaded to this repo, its issues, or its PRs, including as part of a vulnerability report.
- In scope: access-control bypasses, auth/token issues, injection (SQL, prompt), unsafe file handling, leaks of report contents into logs or the LLM.

## Security design summary

- JWT auth with short-lived access tokens; login is rate-limited.
- Object-scoped access: patients see only their own reports, staff only their center's; out-of-scope objects return 404.
- PDFs go to a private S3 bucket via short-lived pre-signed URLs; size, content type and `%PDF-` magic bytes are verified.
- Only redacted text reaches Claude, and only with explicit, withdrawable consent. Report text is treated as data, output is schema-constrained and re-validated.
- Append-only audit log for every access to patient data; erasure deletes files before database rows.
- Secrets come from environment variables; the Docker image runs as non-root.

Rationale for each choice is in [DECISIONS.md](DECISIONS.md) and [README.md](README.md#privacy-safety-and-security).
