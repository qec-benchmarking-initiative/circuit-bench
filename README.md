# DecoderBench

An open registry and benchmark specification for quantum error-correction
decoders.

The project is currently in the design phase.

- [Complete relational data model 0.1](docs/data-model-0.1.md)
- [Development plan](docs/development-plan.md)
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
