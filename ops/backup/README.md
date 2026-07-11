# Nightly MongoDB backup

A Cloud Run **Job** that `mongodump`s the whole database to a GCS bucket,
triggered daily by Cloud Scheduler. Restores use `mongorestore`:

```
gcloud storage cp gs://reliafy-backups/mongodump-<date>.archive.gz - \
  | mongorestore --uri "$MONGODB_URI" --archive --gzip --drop
```

## One-time setup (already applied to reliafy-app)

```
# Bucket with a 30-day retention window
gcloud storage buckets create gs://reliafy-backups \
  --location=australia-southeast1 --uniform-bucket-level-access
gcloud storage buckets update gs://reliafy-backups \
  --lifecycle-file=ops/backup/lifecycle.json

# Build the job image
gcloud builds submit ops/backup \
  --tag australia-southeast1-docker.pkg.dev/reliafy-app/cloud-run-source-deploy/reliafy-backup

# Create the job (MONGODB_URI mirrors the service's env)
gcloud run jobs create reliafy-backup \
  --image australia-southeast1-docker.pkg.dev/reliafy-app/cloud-run-source-deploy/reliafy-backup \
  --region australia-southeast1 \
  --set-env-vars "BACKUP_BUCKET=gs://reliafy-backups" \
  --set-env-vars "MONGODB_URI=<atlas uri>" \
  --max-retries 1 --task-timeout 15m

# Daily at 03:10 Brisbane
gcloud scheduler jobs create http reliafy-backup-nightly \
  --location australia-southeast1 \
  --schedule "10 3 * * *" --time-zone "Australia/Brisbane" \
  --uri "https://run.googleapis.com/v2/projects/reliafy-app/locations/australia-southeast1/jobs/reliafy-backup:run" \
  --http-method POST \
  --oauth-service-account-email <project number>-compute@developer.gserviceaccount.com
```

Run on demand: `gcloud run jobs execute reliafy-backup --region australia-southeast1`.
