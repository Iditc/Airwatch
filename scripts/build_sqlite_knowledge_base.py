"""Build the local AirWatch SQLite knowledge base from the five JSON exports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, NoReturn

Row = dict[str, Any]
DATA_DIR = Path(__file__).resolve().parents[1] / "data/knowledge_base"
SCHEMA = Path(__file__).with_name("knowledge_base_schema.sql")

# The load order keeps referenced rows available before their links are inserted.
DATASETS = (
    ("mechanism_sources", "research_sources", "source_id title url doi"),
    (
        "cases",
        "historical_records",
        "id kind category title country region start_date end_date source_url",
    ),
    ("mechanisms", "mechanisms", "id title topic geographic_scope review_status"),
    (
        "diagnostic_inputs",
        "diagnostic_inputs",
        "id name schema_availability availability_at_event_time",
    ),
    ("diagnostic_checks", "diagnostic_checks", "id title review_status"),
)
POLLUTANT_LINKS = {
    "cases": "historical_record_pollutants",
    "mechanisms": "mechanism_pollutants",
    "diagnostic_checks": "diagnostic_check_pollutants",
}
EVIDENCE_TABLES = {
    "mechanisms": "mechanism_evidence",
    "diagnostic_checks": "diagnostic_check_evidence",
}
EVIDENCE_FIELDS = (
    "id",
    "source_id",
    "claim",
    "locator",
    "evidence_type",
    "verification_status",
    "verification_note",
)


def unique_object(pairs: list[tuple[str, Any]]) -> Row:
    result: Row = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def reject_constant(value: str) -> NoReturn:
    raise ValueError(f"invalid JSON number {value}")


def text(row: Row, field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value


def text_list(row: Row, field: str) -> list[str]:
    value = row.get(field)
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"{field} must be a list of nonempty strings")
    return value


def objects(row: Row, field: str) -> list[Row]:
    value = row.get(field)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{field} must be a list of objects")
    return value


def link(
    db: sqlite3.Connection, table: str, owner_id: str, targets: list[str], *, reverse: bool = False
) -> None:
    if len(set(targets)) != len(targets):
        raise ValueError(f"{table} contains a duplicate reference")
    pairs = ((target, owner_id) if reverse else (owner_id, target) for target in targets)
    db.executemany(f"INSERT INTO {table} VALUES (?, ?)", pairs)


def load_evidence(db: sqlite3.Connection, dataset: str, row: Row) -> None:
    owner_id = text(row, "id")
    table = EVIDENCE_TABLES[dataset]
    items = objects(row, "evidence")
    if not items:
        raise ValueError("evidence must contain at least one item")
    for item in items:
        db.execute(
            f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (owner_id, *(text(item, field) for field in EVIDENCE_FIELDS)),
        )

    evidence_ids = {item["id"] for item in items}
    signal_fields = (
        ("expected_signals", "contradicting_signals")
        if dataset == "mechanisms"
        else ("interpretations",)
    )
    for field in signal_fields:
        for signal in objects(row, field):
            text(signal, "observation" if dataset == "mechanisms" else "explanation")
            if text(signal, "basis") not in {"reported_finding", "synthesis"}:
                raise ValueError(f"{field} has an invalid evidence basis")
            missing = set(text_list(signal, "evidence_ids")) - evidence_ids
            if missing:
                raise ValueError(f"{field} has unknown evidence IDs: {', '.join(sorted(missing))}")

    if dataset == "mechanisms":
        listed = text_list(row, "source_ids")
        actual = {item["source_id"] for item in items}
        if len(listed) != len(actual) or set(listed) != actual:
            raise ValueError("source_ids must match the sources cited by the mechanism evidence")
        for finding in objects(row, "quantitative_findings"):
            if type(finding.get("value")) not in (int, float):
                raise ValueError("quantitative_findings.value must be a JSON number")
            evidence_id = text(finding, "evidence_id")
            if evidence_id not in evidence_ids:
                raise ValueError(f"quantitative finding has unknown evidence ID {evidence_id!r}")
            for field in ("pollutant", "finding", "unit", "statistic", "scope"):
                text(finding, field)


def index_values(dataset: str, row: Row, columns: str) -> tuple[str | None, ...]:
    projected = row
    if dataset == "mechanism_sources" and row.get("doi") == "":
        # Task 2 used an empty DOI for some sources. Keep it in the JSON payload.
        projected = {**row, "doi": None}
    if dataset == "mechanisms":
        applicability = row.get("applicability")
        if not isinstance(applicability, dict):
            raise ValueError("applicability must be an object")
        projected = {**row, "geographic_scope": text(applicability, "geographic_scope")}
        for field in ("countries", "regions", "seasons", "station_types", "transfer_limitations"):
            text_list(applicability, field)
        text(row, "summary")
        text(row, "mechanism_explanation")
        for item in objects(row, "required_context"):
            text(item, "input")
            text(item, "purpose")
            if type(item.get("available_in_current_schema")) is not bool:
                raise ValueError("required_context.available_in_current_schema must be a boolean")
    if dataset == "cases":
        text(row, "summary")
        text(row, "investigation_hint")
        for field in ("expected_signals", "contradicting_signals", "required_context"):
            text_list(row, field)
        for field in ("start_date", "end_date"):
            if row.get(field) is not None:
                value = text(row, field)
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError(f"{field} must be a YYYY-MM-DD date")
    if dataset == "diagnostic_checks":
        text(row, "trigger_pattern")
        text_list(row, "procedure")

    nullable = {"start_date", "end_date", "doi"}
    return tuple(
        None if field in nullable and projected.get(field) is None else text(projected, field)
        for field in columns.split()
    )


def import_dataset(
    db: sqlite3.Connection, path: Path, dataset: str, table: str, columns: str
) -> int:
    raw = path.read_bytes()
    try:
        records = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant
        )
        if not isinstance(records, list):
            raise ValueError("expected a JSON array")
    except ValueError as error:
        raise ValueError(f"{path.name}: {error}") from error

    placeholders = ", ".join("?" for _ in range(len(columns.split()) + 1))
    column_names = ", ".join(columns.split() + ["payload_json"])
    for index, row in enumerate(records, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"{path.name} record {index}: expected a JSON object")
        try:
            values = index_values(dataset, row, columns)
            row_id = text(row, columns.split()[0])
            payload = json.dumps(row, ensure_ascii=False, allow_nan=False)
            db.execute(
                f"INSERT INTO {table} ({column_names}) VALUES ({placeholders})", (*values, payload)
            )
            if dataset in POLLUTANT_LINKS:
                pollutants = text_list(row, "pollutants")
                if not pollutants:
                    raise ValueError("pollutants must contain at least one tag")
                link(db, POLLUTANT_LINKS[dataset], row_id, pollutants)
            if dataset in EVIDENCE_TABLES:
                load_evidence(db, dataset, row)
            if dataset == "diagnostic_checks":
                link(
                    db,
                    "mechanism_diagnostic_checks",
                    row_id,
                    text_list(row, "mechanism_ids"),
                    reverse=True,
                )
                link(db, "diagnostic_check_inputs", row_id, text_list(row, "input_ids"))
            if dataset == "diagnostic_inputs":
                link(db, "diagnostic_input_sources", row_id, text_list(row, "source_ids"))
        except (ValueError, sqlite3.IntegrityError) as error:
            identity = row.get(columns.split()[0])
            raise ValueError(f"{path.name} record {index} ({identity!r}): {error}") from error

    db.execute(
        "INSERT INTO import_manifest VALUES (?, ?, ?)",
        (path.name, hashlib.sha256(raw).hexdigest(), len(records)),
    )
    return len(records)


def verify_database(db: sqlite3.Connection) -> None:
    for source_id, payload in db.execute("SELECT source_id, payload_json FROM research_sources"):
        actual = {
            row[0]
            for row in db.execute(
                "SELECT DISTINCT mechanism_id FROM mechanism_evidence WHERE source_id = ?",
                (source_id,),
            )
        }
        try:
            listed = text_list(json.loads(payload), "record_ids")
            if len(listed) != len(actual) or set(listed) != actual:
                raise ValueError("record_ids must match the mechanisms citing this source")
        except ValueError as error:
            raise ValueError(
                f"air_pollution_mechanism_sources.json ({source_id!r}): {error}"
            ) from error
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("SQLite foreign key check failed")
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("SQLite integrity check failed")


def build_database(source_dir: Path, output: Path) -> dict[str, int]:
    """Build and verify an index before replacing the destination database."""

    output = output.resolve()
    paths = [source_dir / f"air_pollution_{dataset}.json" for dataset, _, _ in DATASETS]
    if output in {path.resolve() for path in [*paths, SCHEMA]}:
        raise ValueError("database path must differ from the source and schema files")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as staging:
        temporary_db = Path(staging) / "knowledge_base.sqlite3"
        with closing(sqlite3.connect(temporary_db)) as db:
            db.executescript(SCHEMA.read_text(encoding="utf-8"))
            with db:
                counts = {
                    table: import_dataset(db, path, dataset, table, columns)
                    for path, (dataset, table, columns) in zip(paths, DATASETS, strict=True)
                }
                verify_database(db)
                db.execute("ANALYZE")
        os.replace(temporary_db, output)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=DATA_DIR / "knowledge_base.sqlite3")
    args = parser.parse_args()
    try:
        counts = build_database(args.source_dir, args.output)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"Error building the knowledge base: {error}", file=sys.stderr)
        return 1
    for table, count in counts.items():
        print(f"{table}: {count}")
    print(f"Wrote {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
