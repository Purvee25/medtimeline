# Contributing

Thanks for your interest. MedTimeline is a portfolio project; issues and small, focused PRs are welcome.

> All data in this repo must be synthetic. Never commit or upload real lab reports or any other personal health information.

## Development setup

**Backend** (Python 3.13, Postgres, Redis, `tesseract`, `poppler`):

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
createdb medtimeline && .venv/bin/python manage.py migrate --settings=config.settings_test
.venv/bin/celery -A config worker   # separate terminal, only needed for extraction
```

**Frontend** (Node 24):

```bash
cd frontend && npm ci
npm run dev        # http://localhost:5173, proxies /api to Django on :8000
```

Or run everything with Docker: see [Quickstart (Docker)](README.md#quickstart-docker).

## Checks

Run the same checks CI runs before opening a PR.

**Backend** (from the repo root, venv active):

```bash
ruff check .
black --check --exclude '/(\.venv|migrations)/' .   # drop --check to format
python manage.py makemigrations --check --dry-run --settings=config.settings_test
pytest -q
```

**Frontend** (from `frontend/`):

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

## Branches and commits

- Branch from `main` with a descriptive name, e.g. `feat/hba1c-trend`, `fix/review-validation`.
- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`. Keep commits small and atomic; explain the *why* in the body.
- Record non-obvious design trade-offs in [DECISIONS.md](DECISIONS.md).

## Pull requests

The CI jobs **`test`** and **`frontend`** are required and must pass before merge.

Checklist:

- [ ] Focused change with a clear description and linked issue (if any)
- [ ] Tests added or updated; a regression test for every bug fix
- [ ] Backend and frontend checks above pass locally
- [ ] Migrations included for model changes
- [ ] Docs (README, DECISIONS.md) updated if behaviour changed
- [ ] No secrets, no real patient data
