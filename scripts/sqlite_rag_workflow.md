# SQLite retrieval and RAG context preparation

Run commands from the repository root with the project's Python environment.
Use Python 3.10 or later. This pipeline uses Python's SQLite library and the
project's Pydantic models. All input exports and generated databases are local.

## Build the database

Place these five exports from issue #7 in `data/knowledge_base`:

- `air_pollution_cases.json`
- `air_pollution_mechanisms.json`
- `air_pollution_mechanism_sources.json`
- `air_pollution_diagnostic_checks.json`
- `air_pollution_diagnostic_inputs.json`

```shell
python -m scripts.build_sqlite_knowledge_base
```

The builder validates identifiers, links and indexed values, preserves complete
records as JSON, and records SHA-256 fingerprints of the inputs. It validates a
temporary database before replacing `data/knowledge_base/knowledge_base.sqlite3`.
Use `--source-dir` and `--output` to select other paths. Close database clients
before replacing a database on Windows.

## Prepare context for the Root Cause Agent

Create a local JSON request matching
`src/schemas/knowledge_retrieval.py::KnowledgeRetrievalRequest`. Supply an
`event` matching `AnomalyEvent`; region, measurement unit, weather, neighbors,
and recent measurement series are optional.

```shell
python -m scripts.prepare_knowledge_context request.json
```

The command prints JSON containing ranked retrieval results, citation metadata,
unresolved inputs, and the original event request. It runs
locally without an API key. The Root Cause Agent in issue #9 can use those
messages for generation and evaluation.

Use `--database` for an alternate database and `--limit` for a different
number of matches per collection. The default is ten per collection.
Python callers can use `retrieve_knowledge` in `src.knowledge_base.retrieval`
or `prepare_rag_context` in `src.knowledge_base.rag`.

## Retrieval behavior

Candidates must include the event pollutant. Historical records with a matching
documented direction rank ahead of unknown or mixed directions, followed by
opposite directions. Region and calendar month refine the ranking.
Mechanisms rank by relevant diagnostic-check rules, region, season and review
status. A rise in particles at the event station and a neighbor promotes
regional-versus-local checks when the series have comparable windows.

These rules select investigation material. Input availability flags report
whether supplied observations suffice for each check. Exact region strings,
unrecognized context inputs, and patterns beyond the implemented rules can
limit ranking. Source quality and verification notes accompany retrieved claims.

## Verify

```shell
python -m pytest -rs
```

Unit tests use synthetic exports and temporary databases. Five integration
scenarios require the local database. Pytest reports them as skipped when it
is missing; `-rs` displays the reason.
