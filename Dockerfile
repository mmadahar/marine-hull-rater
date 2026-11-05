FROM python:3.14-slim

ENV UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv==0.13.0

WORKDIR /srv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

# The project runs from these folders. rates/ must sit alongside rater/.
COPY rater ./rater
COPY rates ./rates
COPY app ./app

# Files stay owned by root, so the running app can't change them.
RUN useradd --create-home --uid 1000 app
USER app

ARG GIT_COMMIT=local
ENV GIT_COMMIT=$GIT_COMMIT

EXPOSE 8000
# --no-proxy-headers: rate limiting reads X-Forwarded-For itself (app/rate_limit.py).
# --no-access-log: stdout carries only the audit trail.
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log"]
