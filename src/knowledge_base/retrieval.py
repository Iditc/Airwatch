"""Retrieve knowledge-base records and citations for an AirWatch anomaly."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import date, timezone
from math import isfinite
from typing import TYPE_CHECKING, Any, Literal

from src.schemas.knowledge_retrieval import (
    DiagnosticInputStatus,
    EventInputStatus,
    HistoricalKnowledgeMatch,
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalResult,
    MechanismKnowledgeMatch,
    RetrievedDiagnosticCheck,
    RetrievedEvidence,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

Record = dict[str, Any]
Status = Literal["available", "missing", "unknown"]
SCHEMA_VERSION = 1
SEASONS = (
    "winter",
    "winter",
    "spring",
    "spring",
    "spring",
    "summer",
    "summer",
    "summer",
    "autumn",
    "autumn",
    "autumn",
    "winter",
)
REVIEW_ORDER = {"verified": 0, "partially_verified": 1, "unverified": 2}
WEATHER_FIELDS = {
    "wind_direction": "wind_direction",
    "wind_speed": "wind_speed_kmh",
    "temperature": "temperature_c",
    "humidity": "humidity_pct",
    "relative_humidity": "humidity_pct",
    "weather_conditions": "conditions",
}
NEIGHBOR_FIELDS = {
    "neighboring_station_values",
    "neighboring_station_distances",
    "neighboring_station_anomaly_flags",
}
EVENT_FIELDS = {
    "pollutant",
    "measured_value",
    "baseline_value",
    "anomaly_score",
    "severity",
    "timestamp",
    "station_id",
    "station_name",
    "station_id_and_name",
    "latitude",
    "longitude",
}
CLOCK_FIELDS = {"hour_of_day", "day_of_week", "season"}
PARTICLE_CHECKS = (
    "dc-dust-vs-local-pm",
    "dc-single-station-artifact-vs-regional-signal",
)


def matching_records(
    db: sqlite3.Connection, collection: Literal["historical", "mechanisms"], pollutant: str
) -> list[Record]:
    if collection == "historical":
        query = """
            SELECT r.payload_json FROM historical_record_pollutants AS p
            JOIN historical_records AS r ON r.id = p.historical_record_id
            WHERE p.pollutant = ?
        """
    else:
        query = """
            SELECT m.payload_json FROM mechanism_pollutants AS p
            JOIN mechanisms AS m ON m.id = p.mechanism_id
            WHERE p.pollutant = ?
        """
    return [json.loads(row[0]) for row in db.execute(query, (pollutant,))]


def select_for_ids(
    db: sqlite3.Connection, query: str, ids: list[str], *params: str
) -> list[sqlite3.Row]:
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    return db.execute(query.format(ids=placeholders), (*ids, *params)).fetchall()


def historical_rank(
    record: Record, request: KnowledgeRetrievalRequest
) -> tuple[tuple[int, bool, bool, str], list[str]]:
    pollutant = request.event.pollutant.value
    delta = request.event.value - request.event.baseline_value
    documented = {
        change.get("direction")
        for change in record.get("documented_changes", [])
        if change.get("pollutant") == pollutant
    } & {"increase", "decrease"}
    direction_rank = 1
    matched_on = [f"Pollutant: {pollutant}"]
    if delta and len(documented) == 1:
        direction = "increase" if delta > 0 else "decrease"
        if direction in documented:
            direction_rank = 0
            matched_on.append(f"Documented {pollutant} {direction}")
        else:
            direction_rank = 2

    region_match = (
        request.region is not None and record["region"].casefold() == request.region.casefold()
    )
    same_month = False
    if record["kind"] == "historical_event":
        start, end = (date.fromisoformat(record[field]) for field in ("start_date", "end_date"))
        same_month = (start.year, start.month) == (end.year, end.month)
        same_month = same_month and start.month == request.event.timestamp.month
    if region_match:
        matched_on.append(f"Same region: {request.region}")
    if same_month:
        matched_on.append("Historical event in the same calendar month")
    return (direction_rank, not region_match, not same_month, record["id"]), matched_on


def mechanism_rank(
    record: Record, request: KnowledgeRetrievalRequest, check_priority: int | None
) -> tuple[tuple[int, bool, bool, int, str], list[str]]:
    applicability = record["applicability"]
    region_match = request.region is not None and request.region.casefold() in {
        region.casefold() for region in applicability["regions"]
    }
    season = SEASONS[request.event.timestamp.month - 1]
    # Prefer documented seasonal applicability without excluding records that apply year-round.
    season_match = season in {item.casefold() for item in applicability["seasons"]}
    matched_on = [f"Pollutant: {request.event.pollutant.value}"]
    if check_priority is not None:
        matched_on.append("Linked check for a rise at multiple stations in comparable windows")
    if region_match:
        matched_on.append(f"Documented region: {request.region}")
    if season_match:
        matched_on.append(f"Documented season: {season}")
    return (
        len(PARTICLE_CHECKS) if check_priority is None else check_priority,
        not region_match,
        not season_match,
        REVIEW_ORDER[record["review_status"]],
        record["id"],
    ), matched_on


def comparable_series_changes(request: KnowledgeRetrievalRequest) -> Iterator[tuple[float, float]]:
    """Yield endpoint changes over shared windows for the event station and a neighbor."""
    series = [
        item
        for item in request.recent_measurement_series or []
        if item.pollutant == request.event.pollutant and len(item.measurements) >= 2
    ]
    focal = [item for item in series if item.station_id == request.event.station_id]
    for primary in focal:
        if primary.averaging_period_seconds is None:
            continue
        primary_values = {
            point.timestamp.astimezone(timezone.utc): point.value for point in primary.measurements
        }
        for neighbor in series:
            if (
                neighbor.station_id == primary.station_id
                or neighbor.unit != primary.unit
                or neighbor.averaging_period_seconds != primary.averaging_period_seconds
            ):
                continue
            neighbor_values = {
                point.timestamp.astimezone(timezone.utc): point.value
                for point in neighbor.measurements
            }
            shared = sorted(primary_values.keys() & neighbor_values.keys())
            if len(shared) >= 2:
                first, last = shared[0], shared[-1]
                yield (
                    primary_values[last] - primary_values[first],
                    (neighbor_values[last] - neighbor_values[first]),
                )


def recent_series_status(request: KnowledgeRetrievalRequest) -> tuple[Status, str]:
    if context_status("raw_time_series", request) == "missing":
        return (
            "missing",
            "At least two recent readings for the event station and pollutant are needed.",
        )
    if next(comparable_series_changes(request), None) is not None:
        return "available", "Event and neighbor series share comparable observation windows."
    return (
        "missing",
        "Event-station series supplied. A comparable neighbor series is still missing.",
    )


def context_status(name: str, request: KnowledgeRetrievalRequest) -> Status:
    if name in EVENT_FIELDS:
        return "available"
    if name in CLOCK_FIELDS:
        return "available" if request.event.timestamp.utcoffset() is not None else "unknown"
    if name in WEATHER_FIELDS:
        value = getattr(request.weather, WEATHER_FIELDS[name], None)
        return "available" if value is not None else "missing"
    if name in NEIGHBOR_FIELDS:
        return "available" if request.neighbors else "missing"
    if name == "reporting_units":
        return "available" if request.measurement_unit is not None else "missing"
    if name == "raw_time_series":
        has_series = any(
            item.station_id == request.event.station_id
            and item.pollutant == request.event.pollutant
            and len(item.measurements) >= 2
            for item in request.recent_measurement_series or []
        )
        return "available" if has_series else "missing"
    if name == request.event.pollutant.value:
        return "available"
    return "unknown"


def diagnostic_input(record: Record, request: KnowledgeRetrievalRequest) -> DiagnosticInputStatus:
    input_id = record["id"]
    status: Status = "unknown"
    detail = None
    if input_id == "in-station-time-series":
        status, detail = recent_series_status(request)
    elif record["schema_availability"] == "direct" and record["schema_fields"]:
        states = {context_status(name, request) for name in record["schema_fields"]}
        if states == {"available"}:
            status = "available"
        elif "missing" in states:
            status = "missing"
            if "available" in states:
                detail = "Some of the input fields were supplied."
    elif input_id == "in-advection-lag-estimate":
        wind = request.weather.wind_speed_kmh if request.weather is not None else None
        if request.neighbors and wind is not None and isfinite(wind) and wind > 0:
            status = "available"
            detail = "Distance and wind speed permit an estimate. Wind alignment needs bearings."
        else:
            status = "missing"
    elif record["schema_availability"] == "additional_data_required":
        status = "missing"

    return DiagnosticInputStatus(
        input_id=input_id,
        name=record["name"],
        status=status,
        detail=detail,
        documentation_url=record.get("documentation_url") or None,
    )


def citations(
    db: sqlite3.Connection, owner_ids: list[str], *, diagnostic: bool
) -> dict[str, list[RetrievedEvidence]]:
    table, owner = (
        ("diagnostic_check_evidence", "check_id")
        if diagnostic
        else ("mechanism_evidence", "mechanism_id")
    )
    query = f"""
        SELECT e.{owner} AS owner_id, e.evidence_id, e.claim, e.source_id,
               s.title AS source_title, s.url AS source_url, e.locator,
               e.verification_status, e.verification_note
        FROM {table} AS e
        JOIN research_sources AS s ON s.source_id = e.source_id
        WHERE e.{owner} IN ({{ids}})
        ORDER BY e.{owner}, e.evidence_id
    """
    grouped: dict[str, list[RetrievedEvidence]] = defaultdict(list)
    for row in select_for_ids(db, query, owner_ids):
        grouped[row["owner_id"]].append(RetrievedEvidence.model_validate(dict(row)))
    return grouped


def diagnostic_checks(
    db: sqlite3.Connection,
    mechanism_ids: list[str],
    request: KnowledgeRetrievalRequest,
    priorities: dict[str, int],
) -> dict[str, list[RetrievedDiagnosticCheck]]:
    rows = select_for_ids(
        db,
        """
        SELECT l.mechanism_id, c.id, c.payload_json
        FROM mechanism_diagnostic_checks AS l
        JOIN diagnostic_checks AS c ON c.id = l.check_id
        JOIN diagnostic_check_pollutants AS p ON p.check_id = c.id
        WHERE l.mechanism_id IN ({ids}) AND p.pollutant = ?
        ORDER BY l.mechanism_id, c.id
        """,
        mechanism_ids,
        request.event.pollutant.value,
    )
    records = {row["id"]: json.loads(row["payload_json"]) for row in rows}
    check_ids = list(records)
    evidence = citations(db, check_ids, diagnostic=True)
    inputs: dict[str, list[DiagnosticInputStatus]] = defaultdict(list)
    for row in select_for_ids(
        db,
        """
        SELECT l.check_id, i.payload_json FROM diagnostic_check_inputs AS l
        JOIN diagnostic_inputs AS i ON i.id = l.input_id
        WHERE l.check_id IN ({ids}) ORDER BY l.check_id, l.input_id
        """,
        check_ids,
    ):
        inputs[row["check_id"]].append(diagnostic_input(json.loads(row["payload_json"]), request))
    assembled = {
        check_id: RetrievedDiagnosticCheck.model_validate(
            {
                **record,
                "check_id": check_id,
                "evidence": evidence.get(check_id, []),
                "required_inputs": inputs.get(check_id, []),
            }
        )
        for check_id, record in records.items()
    }
    grouped: dict[str, list[RetrievedDiagnosticCheck]] = defaultdict(list)
    for row in rows:
        grouped[row["mechanism_id"]].append(assembled[row["id"]])
    for checks in grouped.values():
        checks.sort(key=lambda check: priorities.get(check.check_id, len(priorities)))
    return grouped


def retrieve_knowledge(
    database: Path, request: KnowledgeRetrievalRequest, *, limit: int = 10
) -> KnowledgeRetrievalResult:
    """Retrieve up to `limit` matches per knowledge collection using a read-only snapshot."""
    if limit <= 0:
        raise ValueError("Retrieval limit must be positive")

    pollutant = request.event.pollutant.value
    priorities = {}
    if (
        pollutant in {"pm25", "pm10"}
        and request.event.value > request.event.baseline_value
        and any(
            primary > 0 and neighbor > 0 for primary, neighbor in comparable_series_changes(request)
        )
    ):
        priorities = {check_id: rank for rank, check_id in enumerate(PARTICLE_CHECKS)}
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported knowledge-base schema. Expected version {SCHEMA_VERSION}."
            )

        history = sorted(
            (
                (historical_rank(row, request), row)
                for row in matching_records(db, "historical", pollutant)
            ),
            key=lambda item: item[0][0],
        )[:limit]
        mechanism_priorities: dict[str, int] = {}
        for row in select_for_ids(
            db,
            """
            SELECT l.mechanism_id, l.check_id FROM mechanism_diagnostic_checks AS l
            JOIN diagnostic_check_pollutants AS p ON p.check_id = l.check_id
            WHERE l.check_id IN ({ids}) AND p.pollutant = ?
            """,
            list(priorities),
            pollutant,
        ):
            mechanism_id = row["mechanism_id"]
            mechanism_priorities[mechanism_id] = min(
                mechanism_priorities.get(mechanism_id, len(priorities)), priorities[row["check_id"]]
            )
        mechanisms = sorted(
            (
                (mechanism_rank(row, request, mechanism_priorities.get(row["id"])), row)
                for row in matching_records(db, "mechanisms", pollutant)
            ),
            key=lambda item: item[0][0],
        )[:limit]
        mechanism_ids = [row["id"] for _, row in mechanisms]
        checks = diagnostic_checks(db, mechanism_ids, request, priorities)
        evidence = citations(db, mechanism_ids, diagnostic=False)

    return KnowledgeRetrievalResult(
        event_id=request.event.event_id,
        historical_matches=[
            HistoricalKnowledgeMatch.model_validate(
                {
                    **row,
                    "record_id": row["id"],
                    "matched_on": matched_on,
                }
            )
            for (_, matched_on), row in history
        ],
        mechanism_matches=[
            MechanismKnowledgeMatch.model_validate(
                {
                    **row,
                    "record_id": row["id"],
                    "matched_on": matched_on,
                    "evidence": evidence.get(row["id"], []),
                    "diagnostic_checks": checks.get(row["id"], []),
                    "required_context": [
                        EventInputStatus(
                            name=item["input"],
                            status=context_status(item["input"], request),
                            detail=item["purpose"],
                        )
                        for item in row["required_context"]
                    ],
                }
            )
            for (_, matched_on), row in mechanisms
        ],
    )
