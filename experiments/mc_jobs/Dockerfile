# Worker image for the Monte-Carlo-on-Cloud-Run-Jobs experiments (not the app).
# Build from the repo root:  docker build -f experiments/mc_jobs/Dockerfile .
# Only what a simulation task imports: no Reliafy backend, no web stack, no
# matplotlib, no google-cloud-storage (gcs.py uses the standard library).
# Python 3.12 and the pins in requirements-worker.txt match the launcher, which
# pickles the RBD this image unpickles.
FROM python:3.12-slim
WORKDIR /code

COPY experiments/mc_jobs/requirements-worker.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && pip install --no-cache-dir -r requirements-worker.txt \
    && pip install --no-cache-dir --no-deps \
         "git+https://github.com/derrynknife/SurPyval.git@v0.21.0" \
         "git+https://github.com/derrynknife/RePyability.git@v0.10.1" \
    && python -c "import repyability.rbd.repairable_rbd" \
    && find /usr/local/lib/python3.12/site-packages -depth -type d \( -name tests -o -name test \) \
         -prune -exec rm -rf {} + \
    && python -m pip uninstall -y pip \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/* /root/.cache

ENV PYTHONPATH=/code/experiments/mc_jobs PYTHONUNBUFFERED=1
COPY experiments/mc_jobs/blocks.py experiments/mc_jobs/gcs.py experiments/mc_jobs/tally_io.py experiments/mc_jobs/worker.py ./experiments/mc_jobs/
RUN python -m compileall -q experiments/mc_jobs /usr/local/lib/python3.12

CMD ["python", "experiments/mc_jobs/worker.py"]
