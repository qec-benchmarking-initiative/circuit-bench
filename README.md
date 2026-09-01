# Circuit Bench

An open registry and benchmark specification for quantum error-correction
decoders.

The project has a complete `0.1` relational model and a working local
development foundation. Provider-only accounts, immutable local artifacts,
scientific discovery/comparison views, and the first moderated submission
workflow are implemented.

- [Complete relational data model 0.1](docs/data-model-0.1.md)
- [Development plan](docs/development-plan.md)
- [Submission and approval policy 0.1](docs/submission-governance-0.1.md)
- [Physical Django model mapping](docs/physical-model-mapping.md)
- [Deferred GitHub/ORCID application setup](docs/oauth-application-setup.md)
- [Render/R2 staging deployment](docs/staging-deployment.md)
- [Decoder record schema 0.1](schemas/decoder/0.1.schema.json)
- [Decoder definitions 0.1](definitions/decoder/0.1.md)
- [Result definitions 0.1 (incomplete working draft)](definitions/result/0.1.md)
- [Superseded initial relational proposal](docs/relational-data-model.md)

## Local PostgreSQL

The development database runs in Docker and stores its data in a named volume.
No native PostgreSQL installation is required.

```sh
docker compose up -d database
docker compose ps
docker compose exec database psql -U decoderbench -d decoderbench
```

Stop the server without deleting its data:

```sh
docker compose stop database
```

The checked-in defaults are local-only development credentials. Copy
`.env.example` to `.env` before changing them. Django migrations will create
the physical schema; the database container deliberately contains no
handwritten schema initialization scripts.

## Local application

Python 3.11 and all dependencies are locked with `uv`:

```sh
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py seed_demo --reset
uv run python manage.py seed_plot_demo
uv run python manage.py seed_submission_demo
uv run python manage.py runserver
```

Open the home page at `http://127.0.0.1:8000/`. The development-only component
gallery is at `http://127.0.0.1:8000/dev/components/`, the database-backed
health response is at `/health/`, and the Django admin is at `/admin/`.

The current review surfaces are:

- `/accounts/login/` for the provider-only sign-in controls;
- `/accounts/` for account settings, currently sign-in identities;
- `/artifacts/` for development-only artifact/schema inspection;
- `/decoders/`, `/circuits/`, and `/noise-models/` for public discovery.
- `/submit/` for structured or JSON record entry and preview;
- `/profile/` for pending, published, and withdrawn records, including edit,
  successor, withdrawal, search, sort, and pagination controls;
- `/review/` for the staff-only review work queue and the seven-day withdrawal
  audit table.

With `DEBUG=True`, the sign-in page also offers the two deterministic mock
accounts created by `seed_demo`; no GitHub or ORCID application is required to
exercise the local permissions workflow.

Load complete checked-in schema/definition pairs into an otherwise unoccupied
database as draft releases with:

```sh
uv run python manage.py load_schema_releases --uploader <ACCOUNT_UUID>
```

An existing release is never repointed. Change the version when its contract
changes. Real GitHub/ORCID credentials remain optional until the manual OAuth
smoke test; follow `docs/oauth-application-setup.md` at that point.

Run the complete verification suite with:

```sh
uv run ruff check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
```

## Hosted staging

The version-controlled Render Blueprint deploys the `staging` branch with a
separate PostgreSQL database and Cloudflare R2 artifact storage. Follow the
[staging deployment runbook](docs/staging-deployment.md); no deployment or
provider credential belongs in this repository.
