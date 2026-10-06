# MedTimeline

Diagnostic report ingestion and health timeline. **Current stage:** synthetic data, evaluation harness, Claude extraction pipeline, Django API (auth, roles, consent, S3 upload, audit log).

## Quickstart

```bash
pip install -e ".[dev]"
python -m medtimeline_eval.generate --n 40 --out data/synthetic --seed 7
python -m medtimeline_extract.pipeline --reports data/synthetic --out data/predictions  # calls Claude
python -m medtimeline_eval.evaluate --truth data/synthetic --pred data/predictions
pytest
```

## What's here

| Module | Purpose |
|---|---|
| `medtimeline_eval/markers.py` | Marker catalogue: LOINC codes, canonical units, unit conversion, plausible ranges |
| `medtimeline_eval/generate.py` | Renders synthetic PDF reports in 4 layouts with ground-truth JSON |
| `medtimeline_eval/evaluate.py` | Field-level precision/recall/F1 per layout |

**Layouts:** `table_classic`, `alias_alt_units` (marker aliases, mmol/L and lakhs/cumm), `inline_dotted` (no table), `scanned` (raster, rotation, blur, noise).

**Metric:** a field is correct only if marker, value (±1% after canonical conversion) and unit all match. Duplicate or unknown predictions lower precision; a missing prediction file counts every field as missed.

## Extraction pipeline

`medtimeline_extract/`: PDF → text layer (pypdf) or OCR (pdftoppm + Tesseract) → identifier redaction → Claude (`claude-opus-5-5`, structured output validated by Pydantic) → unit normalisation and plausibility checks → `extracted` / `needs_review` / `failed`.

Requires the system tools `tesseract` and `poppler`, plus Claude credentials (`ANTHROPIC_API_KEY`).

**LLM data flow:** only redacted text is sent. Lines that contain patient name, report ID, phone or address, and age/sex values, are removed first; the collection date is kept. Report text is sent inside `<report>` tags, and the prompt treats it as data, not instructions. The output is schema-constrained and validated again in code. A refusal falls back to `claude-opus-4-8` on the server side.

## Django API

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env   # then export the variables
createdb medtimeline && .venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/register/` | Patient sign-up with consent flags |
| `POST /api/auth/token/`, `/token/refresh/` | JWT login (throttled) |
| `GET /api/auth/me/` | Current user and role |
| `POST /api/reports/` | Register a report and get a pre-signed S3 upload |
| `POST /api/reports/{id}/complete/` | Verify the upload (size, PDF magic bytes) |
| `GET /api/reports/`, `/api/reports/{id}/` | List or view reports in the caller's scope |
| `GET /api/reports/{id}/download/` | Short-lived pre-signed download URL |

Design choices and the alternatives rejected are in [DECISIONS.md](DECISIONS.md).

## Data policy

All reports are synthetic and fictional. Real reports are never committed (`.gitignore` blocks `real_reports/` and `*.real.pdf`).
