FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# бустинг из sklearn на каждый predict поднимает OpenMP на все ядра машины; при 40 параллельных запросах
# потоки дерутся за CPU и задержка растёт в разы. Параллелим запросами, а не внутри одного предсказания
ENV OMP_NUM_THREADS=1

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

WORKDIR /app

# слой зависимостей: пересобирается, только когда меняются pyproject.toml или uv.lock
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# слой кода: правка в src/ не трогает слой выше
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
