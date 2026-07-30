FROM python:3.12.13-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12.13-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src

USER app
EXPOSE 8085

CMD ["uvicorn", "agentscope_platform.main:app", "--host", "0.0.0.0", "--port", "8085"]
