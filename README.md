# MedTimeline

Turns diagnostic lab-report PDFs from different centers into one verified, LOINC-coded health timeline.

Patients and diagnostic-center staff upload reports. A background worker extracts the results with OCR and Claude, validates every value, and stores the clean ones. Anything suspicious waits for a human to review. Patients then see each marker as a trend across labs, and can export their whole record as FHIR.

> **Scope:** portfolio and learning project. It doesn't diagnose or give dosing advice, and it's not clinically validated. All data in this repo is synthetic.

## Quickstart (Docker)

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY to enable Claude extraction
docker compose up --build     # API on :8000, Celery worker, Postgres, Redis, local S3
curl localhost:8000/healthz
```

## Quickstart (local)

Requires Python 3.13, Postgres, Redis, `tesseract` and `poppler`.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
createdb medtimeline && .venv/bin/python manage.py migrate --settings=config.settings_test
.venv/bin/pytest                    # 54 tests: unit, API, worker; S3 mocked with moto
.venv/bin/celery -A config worker   # separate terminal
```

## Architecture

```
client ──JWT──▶ Django REST API ──pre-signed POST──▶ client uploads PDF directly to S3
                   │  /complete: verify size + %PDF- magic bytes
                   ▼
             Celery (Redis) ── row-locked claim ──▶ PDF text layer │ OCR (pdftoppm + Tesseract)
                                                   ▼
                                     redact identifiers ──▶ Claude (structured JSON output)
                                                   ▼
                       unit normalisation + plausibility checks (medtimeline_eval/markers.py)
                         │ clean rows                          │ suspicious rows / no date
                         ▼                                     ▼
              Observation (LOINC, canonical unit)      needs_review ──▶ POST /review (human)
                         ▼
             GET /api/trends  ·  GET /api/fhir/Patient/$everything
```

| Package | Responsibility |
|---|---|
| `accounts/` | User roles (patient, center staff), per-purpose consent, JWT auth, erasure |
| `reports/` | Upload flow, extraction task, review, trends, FHIR mapping, audit log |
| `medtimeline_extract/` | PDF → text → redaction → Claude → validated rows (usable without Django) |
| `medtimeline_eval/` | Marker catalogue (LOINC, units, ranges), synthetic report generator, evaluator |

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/register/` | Patient sign-up with explicit consent flags |
| `POST /api/auth/token/`, `/token/refresh/` | JWT login (rate-limited) |
| `GET`, `DELETE /api/auth/me/` | Current user; delete erases the account and all report files |
| `GET`, `POST /api/auth/consents/` | List consents, or grant/withdraw one |
| `POST /api/reports/` | Register a report and get a pre-signed S3 upload |
| `POST /api/reports/{id}/complete/` | Verify the upload and queue extraction |
| `GET /api/reports/`, `/{id}/`, `/{id}/download/` | Reports in the caller's scope; short-lived download URL |
| `GET /api/reports/{id}/observations/` | Stored values plus the raw extraction with validation issues |
| `POST /api/reports/{id}/review/` | Replace values with human-verified ones |
| `GET /api/trends/?marker=crp[&patient=…][&verified_only=true]` | One marker over time, all centers, canonical units |
| `GET /api/fhir/Patient/$everything` | Patient's own record as a FHIR R4 Bundle |
| `GET /healthz` | Liveness and database check |

## Measured results

| What | Result | How to reproduce |
|---|---|---|
| Trend query, 100k observations / 2k patients | **14.86 ms → 0.03 ms** (seq scan → index scan) | `python manage.py explain_trends` |
| Cross-patient / cross-center access | Denied (404) on view, download, complete, review, trends | `tests/test_api.py`, `tests/test_workflow.py` |
| Extraction F1, rule-based baseline (held-out, 40 reports, 178 fields) | **0.960** overall: 1.000 on the 3 digital layouts, 0.829 on scans | `--extractor baseline`, see below |
| Extraction F1, Claude | *Not yet measured: needs API credits* | see below |

To measure extraction accuracy:

```bash
python -m medtimeline_eval.generate --n 40 --out data/synthetic --seed 7
python -m medtimeline_extract.pipeline --extractor baseline --out data/predictions_baseline   # free, no LLM
python -m medtimeline_extract.pipeline --out data/predictions                                 # calls Claude
python -m medtimeline_eval.evaluate --truth data/synthetic --pred data/predictions_baseline
```

**Baseline results.** The OCR unit repair rule was written by looking at the seed 7 reports, so seed 99 is a held-out set nobody looked at while tuning. Quote the held-out numbers.

| Layout | F1, seed 7 (tuning) before → after unit fix | F1, seed 99 (held-out) before → after unit fix |
|---|---|---|
| table_classic | 1.000 → 1.000 | 1.000 → 1.000 |
| alias_alt_units | 1.000 → 1.000 | 1.000 → 1.000 |
| inline_dotted | 1.000 → 1.000 | 1.000 → 1.000 |
| scanned | 0.548 → 0.929 | 0.683 → **0.829** |
| **All** | 0.901 → 0.984 | 0.927 → **0.960** |

**Error analysis.** On scans, OCR reads values correctly; units are what break. Tesseract turns the caret in `10^3/uL` into `4`, `°`, `%` or a curly quote. `normalise_unit` now repairs those, but only when the whole string is plainly a count unit. The remaining misses are left for human review rather than guessed at: units with a lost leading digit (`403/uL`), `mo/L` for `mg/L`, and rows OCR dropped entirely. The perfect digital scores are partly circular, because the rules and the generator share the same marker catalogue. Real reports will be harder, and that is the gap Claude has to prove it closes.

## Privacy, safety and security

- **LLM data flow:** only redacted text reaches Claude. Lines that contain name, report ID, phone or address, and age/sex values, are removed first; the collection date is kept. Extraction runs only with explicit, withdrawable `llm_extraction` consent. Without it, reports go to manual review.
- **Prompt injection:** report text is sent inside `<report>` tags as data. Output is schema-constrained (`messages.parse` + Pydantic), then validated again against unit and plausibility rules. Report text can never trigger an action.
- **Files:** they go in a private bucket via short-lived pre-signed URLs (5 min), with size and content type enforced by S3. After upload, the server checks the PDF magic bytes and deletes rejected files.
- **Access:** reports are filtered by object scope (patients see their own, staff their center's), with tests for each rule. Every create, view, list, download, review, export and erasure is written to an append-only audit log.
- **Data rights:** FHIR export (access and portability), consent withdrawal, and erasure. Erasure deletes files first, so a storage failure can't leave orphaned health data in S3.
- **Reference ranges** shown in trends are generic and flagged `approximate: true`.

## Standards

- Markers are coded with **LOINC**.
- Units are canonicalised (UCUM codes in the FHIR export).
- `Observation` and `DiagnosticReport` follow **FHIR R4**.
- Imaging (DICOM) and HL7 v2 feeds are out of scope.

## Operations

- **Configuration:** everything comes from environment variables (`.env.example`). The app refuses to start without a secret key unless `DEBUG` is on.
- **Docker image:** multi-stage build, runs as a non-root user, with `HEALTHCHECK`. Compose adds health-gated Postgres, Redis and a moto S3 server.
- **Worker:** acks late, prefetch 1, hard time limit. Transient Claude and S3 errors retry 3× with exponential backoff, then the report is marked `failed` with the reason.
- **Logging:** structured; request IDs and token usage are logged for each Claude call, report contents never are.
- **CI** (`.github/workflows/ci.yml`): ruff, black, a check for missing migrations, and the full test suite against Postgres with Tesseract installed.
- **Cost:** Tesseract OCR is free. Each Claude call sends about 1–2k tokens of report text, so the 40-report evaluation costs well under $1. Set an AWS budget alert before deploying.

## Not done yet

- AWS deployment (RDS, S3, ECS or EC2) and a live demo link
- Extraction accuracy numbers (run the commands above with an API key)
- React dashboard, appointment booking, webhooks, medication log

Design trade-offs are recorded in [DECISIONS.md](DECISIONS.md).
