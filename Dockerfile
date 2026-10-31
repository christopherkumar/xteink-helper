# Frontend build stage: builds the CrossPoint PXC converter (vite/TS SPA) from its
# own source tree, wired in via the "frontend-src" build context (see docker-compose.yml)
# so the source isn't duplicated into this repo.
FROM node:20-slim AS frontend-build
WORKDIR /src
COPY --from=frontend-src package.json package-lock.json ./
RUN npm ci
COPY --from=frontend-src . .
RUN npm run build

FROM python:3.12-slim
RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY main.py app.py ./
COPY --from=frontend-build /src/dist ./static

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8085/health')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8085"]
