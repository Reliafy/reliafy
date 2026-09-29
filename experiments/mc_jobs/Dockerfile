# Worker image for the Monte-Carlo-on-Cloud-Run-Jobs experiments (not the app).
# Build from the repo root:  docker build -f experiments/mc_jobs/Dockerfile .
# Same library pins as the app image (SurPyval via requirements.txt,
# RePyability v0.10.1 --no-deps), minus the web/auth extras, plus GCS.
FROM python:3.11-slim
WORKDIR /code

COPY requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && grep -viE '^firebase-admin' requirements.txt > /tmp/requirements-runtime.txt \
    && pip install --no-cache-dir -r /tmp/requirements-runtime.txt \
    && pip install --no-cache-dir --no-deps "git+https://github.com/derrynknife/RePyability.git@v0.10.1" \
    && pip install --no-cache-dir "google-cloud-storage==2.18.2" \
    && python -c "import surpyval, repyability, google.cloud.storage" \
    && apt-get purge -y --auto-remove git build-essential \
    && rm -rf /var/lib/apt/lists/* /root/.cache /tmp/requirements-runtime.txt

ENV MPLBACKEND=Agg PYTHONPATH=/code:/code/experiments/mc_jobs PYTHONUNBUFFERED=1
COPY backend/ ./backend/
COPY experiments/mc_jobs/ ./experiments/mc_jobs/
RUN python -m compileall -q backend experiments/mc_jobs

CMD ["python", "experiments/mc_jobs/worker.py"]
