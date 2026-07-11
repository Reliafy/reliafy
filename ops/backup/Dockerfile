# Nightly MongoDB backup job: mongodump piped straight to a GCS bucket.
# Runs as a Cloud Run Job (see ops/backup/README.md).
FROM google/cloud-sdk:slim

RUN apt-get update && apt-get install -y --no-install-recommends wget ca-certificates \
    && wget -q https://fastdl.mongodb.org/tools/db/mongodb-database-tools-debian12-x86_64-100.9.5.deb \
    && apt-get install -y ./mongodb-database-tools-*.deb \
    && rm -f mongodb-database-tools-*.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY backup.sh /backup.sh
RUN chmod +x /backup.sh

ENTRYPOINT ["/bin/bash", "/backup.sh"]
