# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm AS build
WORKDIR /app
RUN python -m venv /venv
ENV PATH=/venv/bin:$PATH
COPY pyproject.toml ./
# Install pinned dependencies first so the layer is cached across source changes.
RUN pip install --no-cache-dir $(python -c "import tomllib; print(' '.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))")
COPY . .
RUN pip install --no-cache-dir --no-deps .

FROM python:3.13-slim-bookworm AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
COPY --from=build /venv /venv
COPY --chown=app:app . /app
WORKDIR /app
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.settings
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8000/healthz || exit 1
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
