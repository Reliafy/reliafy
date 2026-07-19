# ---- Stage 1: build the React frontend ----
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Self-host builds pass --build-arg VITE_AUTH_DISABLED=true (docker-compose does
# this) to bake single-user mode into the bundle: no login, no marketing pages.
# Cloud builds omit it, so the committed frontend/.env.production (Firebase
# login) applies — Vite gives real env vars priority over .env files.
ARG VITE_AUTH_DISABLED=false
ENV VITE_AUTH_DISABLED=${VITE_AUTH_DISABLED}
RUN npm run build
# Cloud builds also prerender the marketing pages (landing/blog/legal) to
# static HTML for search indexing, plus sitemap.xml and robots.txt. Self-host
# builds skip it — they have no marketing pages.
RUN if [ "$VITE_AUTH_DISABLED" != "true" ]; then npm run prerender; fi

# ---- Stage 2: Python backend serving the built frontend ----
FROM python:3.11-slim
WORKDIR /code

# git installs SurPyval/RePyability from their repos; build-essential covers any
# dependency that compiles from source. Both are build-time only and removed
# afterwards to keep the runtime image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# RePyability is installed --no-deps: its metadata pins surpyval>=0.13,<0.14, but
# no surpyval version satisfies that (0.12.0 -> 0.14.0, no 0.13.x). The code runs
# fine against our surpyval 0.12.0 pin; its real deps are in requirements.txt.
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps "git+https://github.com/derrynknife/RePyability.git@0a82ceeab4b7d1fe23caa333f30522aabdc698a2" \
    && apt-get purge -y git build-essential && apt-get autoremove -y

COPY backend/ ./backend/
COPY --from=frontend /frontend/dist ./frontend/dist

# Cloud Run injects $PORT (default 8080); fall back to 8000 for local runs.
EXPOSE 8080
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
