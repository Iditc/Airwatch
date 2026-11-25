"""Validate Task 2 research and export JSON arrays for later database import."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

Row = dict[str, Any]
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
POLLUTANTS = {"pm25", "pm10", "no2", "so2", "co", "o3"}
# These labels are marked available in the research but need extra data in
# AnomalyEvent, InvestigationRequest, WeatherContext, and NeighborStatus.
CONTEXT_NEEDING_DATA = {
    "station_type",
    "station_metadata",
    "hourly_pm",
    "raw_hourly_values",
    "raw_time_series",
    "co_pollutant_values",
    *POLLUTANTS,
}
DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[1] / "data/knowledge_base/research/air_pollution_mechanisms"
)


def unique_keys(pairs: list[tuple[str, Any]]) -> Row:
    result: Row = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON number {value}")


def load_rows(root: Path, pattern: str, id_field: str) -> list[Row]:
    files = sorted(root.glob(pattern))
    if not files:
        raise ValueError(f"no inputs matching {pattern} in {root}")

    rows: list[Row] = []
    seen: set[str] = set()
    for path in files:
        with path.open(encoding="utf-8") as handle:
            lines = handle.readlines()
        if not 0 < len(lines) < 300:
            raise ValueError(f"{path.name}: expected 1–299 physical lines")
        for number, line in enumerate(lines, start=1):
            try:
                row = json.loads(
                    line, object_pairs_hook=unique_keys, parse_constant=reject_constant
                )
                if not isinstance(row, dict):
                    raise ValueError("expected a JSON object")
                identity = row.get(id_field)
                if not isinstance(identity, str) or not ID.fullmatch(identity):
                    raise ValueError(f"invalid {id_field}: {identity!r}")
                if identity in seen:
                    raise ValueError(f"duplicate {id_field}: {identity}")
                seen.add(identity)
                rows.append(row)
            except ValueError as error:
                raise ValueError(f"{path.name}:{number}: {error}") from error
    return rows


def nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_import(records: list[Row], sources: list[Row]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    source_map = {s["source_id"]: s for s in sources}
    dois: dict[str, str] = {}

    for source in sources:
        doi = source.get("doi")
        if doi:
            key = doi.strip().lower().removeprefix("https://doi.org/")
            other_id = dois.setdefault(key, source["source_id"])
            if other_id != source["source_id"]:
                errors.append(f"{source['source_id']}: DOI also assigned to {other_id}")
        if len(set(source["record_ids"])) != len(source["record_ids"]):
            errors.append(f"{source['source_id']}: duplicate record reference")

    covered: set[str] = set()
    for record in records:
        rid = record["id"]
        tags = record["pollutants"]
        if not tags or len(set(tags)) != len(tags):
            errors.append(f"{rid}: pollutant tags must be nonempty and unique")
        covered.update(tags)
        evidence = {item["id"]: item for item in record["evidence"]}

        for item in evidence.values():
            evidence_source = source_map.get(item["source_id"])
            if evidence_source is None:
                errors.append(f"{rid}/{item['id']}: unknown source {item['source_id']}")
                continue
            if (
                item["verification_status"] == "verified"
                and evidence_source["access_level"] != "full_text"
            ):
                errors.append(f"{rid}/{item['id']}: verified evidence requires full-text access")
            if item["evidence_type"] == "official_assessment":
                warnings.append(f"{rid}/{item['id']}: evidence type outside Task 2 enum")

        for signal in record["expected_signals"] + record["contradicting_signals"]:
            if not nonempty_text(signal.get("observation")) or not signal.get("evidence_ids"):
                errors.append(f"{rid}: signal requires an observation and evidence references")

        for index, finding in enumerate(record["quantitative_findings"], start=1):
            location = f"{rid}/quantitative_findings[{index}]"
            value = finding.get("value")
            if type(value) not in (int, float) or (
                isinstance(value, float) and not math.isfinite(value)
            ):
                errors.append(f"{location}: value must be a finite number")
            if finding.get("pollutant") not in tags:
                errors.append(f"{location}: pollutant must be tagged on the record")
            for field in ("finding", "unit", "statistic", "scope"):
                if not nonempty_text(finding.get(field)):
                    errors.append(f"{location}: {field} must contain text")
            for field in ("averaging_period", "comparison_baseline"):
                if field in finding and not nonempty_text(finding[field]):
                    errors.append(f"{location}: omit {field} if undocumented")
            evidence_item = evidence.get(finding.get("evidence_id"))
            if evidence_item is None or evidence_item["verification_status"] != "verified":
                errors.append(f"{location}: quantitative finding needs verified evidence")

        missing_inputs = set()
        for context in record["required_context"]:
            available = context.get("available_in_current_schema")
            if type(available) is not bool:
                errors.append(f"{rid}: available_in_current_schema must be a Boolean")
            if available is True and context["input"] in CONTEXT_NEEDING_DATA:
                missing_inputs.add(context["input"])
        if missing_inputs:
            inputs = ", ".join(sorted(missing_inputs))
            warnings.append(f"{rid}: check schema availability for {inputs}")

    if covered != POLLUTANTS:
        errors.append(f"expected all six pollutant tags, found {sorted(covered)}")
    return errors, warnings


def write_exports(destination: Path, records: list[Row], sources: list[Row]) -> None:
    datasets = {
        "air_pollution_mechanisms.json": records,
        "air_pollution_mechanism_sources.json": sources,
    }
    # Serialize both datasets before touching either output.
    payloads = {
        name: json.dumps(rows, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        for name, rows in datasets.items()
    }
    destination.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        path = destination / name
        path.write_text(payload, encoding="utf-8", newline="\n")
        if json.loads(path.read_text(encoding="utf-8")) != datasets[name]:
            raise ValueError(f"{path}: JSON round trip changed the input data")
        print(f"Wrote {len(datasets[name])} objects to {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, help="Write JSON arrays after validation")
    args = parser.parse_args()
    try:
        records = load_rows(args.source_dir, "air_pollution_mechanisms_*.jsonl", "id")
        sources = load_rows(args.source_dir, "source_inventory*.jsonl", "source_id")
        errors, warnings = validate_import(records, sources)
        for warning in warnings:
            print(f"WARNING {warning}")
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        if errors:
            return 1
        # Keep the research validator authoritative for evidence links, locators,
        # status rollups and the canonical embedding text.
        sys.stdout.flush()
        subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "scripts.validate_task2_mechanism_research",
                str(args.source_dir),
            ],
            check=True,
        )
        if args.output_dir is not None:
            write_exports(args.output_dir, records, sources)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    print(f"Import checks passed for {len(records)} mechanisms and {len(sources)} sources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
