# Staging deployment

Circuit Bench staging is a production-shaped but explicitly non-production
installation. It uses the `staging` Git branch, Render Web Services, a separate
Render PostgreSQL database, and a private Cloudflare R2 bucket. The visible
banner warns that the records are synthetic and are not a permanent scientific
record.

The repository contains the complete deployment definition in `render.yaml`.
Do not copy credentials into that file or into Git: Render prompts for every
secret marked `sync: false` and stores it as an environment variable.

## 1. Create the R2 bucket

The staging Blueprint is configured for the private R2 Standard bucket
`circuit-bench` in Cloudflare account `63b9cf4fbc03f05e1dc6c4e33c421d0a`.
Create an object-storage API token scoped only to read and write objects in that
bucket. The non-secret bucket and endpoint values are already committed:

- `R2_BUCKET_NAME`: `circuit-bench`;
- `R2_ENDPOINT_URL`:
  `https://63b9cf4fbc03f05e1dc6c4e33c421d0a.r2.cloudflarestorage.com`;
- `R2_ACCESS_KEY_ID`: the token's access-key ID;
- `R2_SECRET_ACCESS_KEY`: the token's secret access key.

The endpoint deliberately does not include the trailing `/circuit-bench` path:
the S3 client receives the account endpoint and bucket name separately.

The application uses R2's S3-compatible API. Objects are private and addressed
by their SHA-256 digest; browser downloads pass back through Django and are
re-hashed before they are served.

## 2. Register staging OAuth applications

Create a separate GitHub OAuth app for staging. Once Render has assigned the
service hostname, set its callback URL to:

```text
https://<RENDER_HOSTNAME>/accounts/github/login/callback/
```

For the ORCID sandbox client, add:

```text
https://<RENDER_HOSTNAME>/accounts/orcid/login/callback/
```

The Blueprint defaults to `sandbox.orcid.org`. Change `ORCID_BASE_DOMAIN` and
use production ORCID credentials only when the corresponding production ORCID
client has been registered. The provider secrets are entered in Render, never
committed.

OAuth setup can be deferred for a read-only first launch. If Render requires a
value for an unused provider secret, enter a temporary non-secret sentinel and
do not try that provider until real credentials replace it.

## 3. Apply the Render Blueprint

1. In the Render dashboard, choose **Blueprints → New Blueprint Instance**.
2. Connect `qec-benchmarking-initiative/circuit-bench`.
3. Confirm that Render reads the root `render.yaml`.
4. Enter the four R2 values and the GitHub/ORCID client credentials when
   prompted.
5. Apply the Blueprint.

The Blueprint creates:

- a free, branch-linked `circuit-bench-staging` web service in Frankfurt;
- a durable 1 GB PostgreSQL 17 database on Render's smallest paid compute plan;
- a generated Django secret;
- health checks at `/health/`;
- deploys only after GitHub Actions passes for `staging`;
- migrations on every service start;
- a one-time, idempotent load of the synthetic core, plotting, and submission
  records.

Render's normal service filesystem is ephemeral. It contains collected static
files and temporary upload buffers only. PostgreSQL owns relational state and
R2 owns immutable uploaded bytes.

## 4. Verify the first deployment

Check the Render deploy log for successful migrations, Gunicorn startup, the
`/health/` health check, and the `Staging data ready` initial hook. Then verify:

```text
https://<RENDER_HOSTNAME>/health/
https://<RENDER_HOSTNAME>/results/
https://<RENDER_HOSTNAME>/accounts/login/
```

The health endpoint must return HTTP 200 and `{"status":"ok","database":"ok"}`.
The staging banner should appear on every HTML page. Artifact links from seeded
circuits should download successfully.

After signing in once with a real provider identity, grant the first reviewer
administrative status from the Render shell:

```sh
python manage.py set_account_admin --github EXACT_GITHUB_USERNAME
```

The same command accepts `--orcid EXACT_ORCID_ID` or `--account ACCOUNT_UUID`;
add `--revoke` to remove the permission.

## Routine deployment

Continue ordinary work on feature branches. Merge a known-good commit into
`staging` and push it. GitHub Actions runs the same Ruff, Django, and pytest
checks used locally; Render deploys only after those checks pass. The hosted
database and local database remain completely separate, while committed Django
migrations keep their structures aligned.

The synthetic seed is intentionally enabled only on this staging service. Do
not set `ALLOW_DEMO_SEED=true` on a future production service.
