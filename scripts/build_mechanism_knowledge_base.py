"""Build AirWatch's mechanism research exports from Task 2 and a Task 3 update."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.check_mechanism_import_readiness import Row, load_rows, validate_import

KNOWLEDGE_BASE = Path(__file__).resolve().parents[1] / "data/knowledge_base"


def merge_sources(baseline: list[Row], followup: list[Row], mechanisms: list[Row]) -> list[Row]:
    # Task 3 may update source metadata. Rebuild links from surviving mechanisms.
    sources = {row["source_id"]: {**row, "record_ids": []} for row in baseline + followup}
    for mechanism in mechanisms:
        for sid in mechanism["source_ids"]:
            sources[sid]["record_ids"].append(mechanism["id"])
    for source in sources.values():
        source["record_ids"].sort()
    return list(sources.values())


def build(task2: Path, task3: Path) -> dict[str, list[Row]]:
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "scripts.validate_task2_mechanism_research",
            str(task2),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "scripts.validate_task3_mechanism_research",
            str(task3),
            str(task2),
        ],
        check=True,
    )
    mechanism_pattern = "air_pollution_mechanisms_*.jsonl"
    source_pattern = "source_inventory*.jsonl"
    mechanism_map = {
        row["id"]: row
        for directory in (task2, task3)
        for row in load_rows(directory, mechanism_pattern, "id")
    }
    mechanisms = list(mechanism_map.values())
    sources = merge_sources(
        load_rows(task2, source_pattern, "source_id"),
        load_rows(task3, source_pattern, "source_id"),
        mechanisms,
    )
    checks = load_rows(task3, "diagnostic_checks_*.jsonl", "id")
    inputs = load_rows(task3, "data_inputs_*.jsonl", "id")
    errors, warnings = validate_import(mechanisms, sources)
    for warning in warnings:
        print(f"WARNING {warning}")
    if errors:
        raise ValueError("\n".join(errors))

    return {
        "air_pollution_mechanisms.json": mechanisms,
        "air_pollution_mechanism_sources.json": sources,
        "air_pollution_diagnostic_checks.json": checks,
        "air_pollution_diagnostic_inputs.json": inputs,
    }


def write_exports(exports: dict[str, list[Row]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        temp = Path(stack.enter_context(TemporaryDirectory(dir=output_dir)))
        for name, rows in exports.items():
            path = temp / name
            payload = json.dumps(rows, ensure_ascii=False, allow_nan=False, indent=2)
            path.write_text(payload + "\n", encoding="utf-8", newline="\n")
            if json.loads(path.read_text(encoding="utf-8")) != rows:
                raise ValueError(f"JSON round trip changed {name}")
        for name, rows in exports.items():
            target = output_dir / name
            os.replace(temp / name, target)
            print(f"Wrote {len(rows)} records to {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task2", type=Path, default=KNOWLEDGE_BASE / "research/air_pollution_mechanisms"
    )
    parser.add_argument(
        "--task3", type=Path, default=KNOWLEDGE_BASE / "research/air_pollution_mechanisms_followup"
    )
    parser.add_argument("--output-dir", type=Path, default=KNOWLEDGE_BASE)
    args = parser.parse_args()
    try:
        write_exports(build(args.task2.resolve(), args.task3.resolve()), args.output_dir)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
