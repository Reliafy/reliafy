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

# Everything that needs build tools happens in ONE layer that also removes
# them: a later `apt-get purge` in a separate RUN only hides files, and the image
# (downloaded on every Cloud Run cold start) would still carry them.
#
# - RePyability is installed --no-deps, after the rest, so our git-pinned
#   surpyval stays authoritative (it declares surpyval>=0.16,<0.17 — a ceiling
#   it has never raised, not a real incompatibility; see requirements.txt).
# - firebase-admin is installed --no-deps with only what its auth module needs
#   (google-auth, cachecontrol, pyjwt, requests, httpx): we only verify ID
#   tokens, and its Firestore / Cloud Storage / gRPC dependencies (~60 MB) are
#   never imported.
# - Libraries' own test suites are stripped, and pip is removed: neither is
#   needed at runtime, and together they're ~100 MB.
COPY requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && python -m pip install --no-cache-dir --upgrade pip \
    && grep -viE '^firebase-admin' requirements.txt > /tmp/requirements-runtime.txt \
    && pip install --no-cache-dir -r /tmp/requirements-runtime.txt \
    && pip install --no-cache-dir --no-deps "git+https://github.com/derrynknife/RePyability.git@v0.11" \
    && pip install --no-cache-dir --no-deps "firebase-admin==7.7.0" \
    && pip install --no-cache-dir google-auth cachecontrol "pyjwt[crypto]" requests httpx \
    && python -c "import firebase_admin, firebase_admin.auth, surpyval, repyability" \
    && find /usr/local/lib/python3.11/site-packages -depth -type d \( -name tests -o -name test \) \
         -not -path '*/_pytest/*' -prune -exec rm -rf {} + \
    && python -m pip uninstall -y pip \
    && apt-get purge -y --auto-remove git build-essential \
    && rm -rf /var/lib/apt/lists/* /root/.cache /tmp/requirements-runtime.txt

# No display on the server: skip matplotlib's GUI-backend probing at import.
ENV MPLBACKEND=Agg

COPY backend/ ./backend/
# Precompile our own code so a cold start doesn't byte-compile it.
RUN python -m compileall -q backend
COPY --from=frontend /frontend/dist ./frontend/dist

# Cloud Run injects $PORT (default 8080); fall back to 8000 for local runs.
EXPOSE 8080
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
