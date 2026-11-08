FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

ENV OMP_NUM_THREADS=1

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev

COPY artifact/ artifact/

RUN useradd --no-create-home --uid 10001 app
USER app

# видимое отличие версии образа: попадает в /health (звёздочка 3)
ARG APP_VERSION=1.0
ENV APP_VERSION=${APP_VERSION} PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000
CMD ["uvicorn", "logp.service.app:app", "--host", "0.0.0.0", "--port", "8000"]
