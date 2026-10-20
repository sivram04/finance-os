# Finance OS, deployed: the FastAPI app and the built React app in one Cloud Run service.
# Data is not baked in: at startup the app downloads the daily snapshot from Cloud Storage (finance_os.app.cloud_data).

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY warehouse/metrics/ warehouse/metrics/
COPY warehouse/seeds/ warehouse/seeds/
RUN pip install .
COPY --from=web /web/dist web/dist
# ROOT for finance_os.paths: the data folder is created here at runtime
ENV FINANCE_OS_ROOT=/app \
    FINANCE_OS_WAREHOUSE=/app/data/deploy/finance_os_app.duckdb \
    FINANCE_OS_NO_TRAIN=1
CMD ["sh", "-c", "uvicorn finance_os.app.cloud:app --host 0.0.0.0 --port ${PORT:-8080}"]
