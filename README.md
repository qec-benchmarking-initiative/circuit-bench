# DecoderBench

An open registry and benchmark specification for quantum error-correction
decoders.

The project has a complete `0.1` relational model and a working local
development foundation. Scientific submission and discovery features are not
implemented yet.

- [Complete relational data model 0.1](docs/data-model-0.1.md)
- [Development plan](docs/development-plan.md)
- [Physical Django model mapping](docs/physical-model-mapping.md)
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
uv run python manage.py runserver
```

Open the home page at `http://127.0.0.1:8000/`. The development-only component
gallery is at `http://127.0.0.1:8000/dev/components/`, the database-backed
health response is at `/health/`, and the Django admin is at `/admin/`.

Run the complete verification suite with:

```sh
uv run ruff check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
```
