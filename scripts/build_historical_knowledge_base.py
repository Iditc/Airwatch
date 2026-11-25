from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    ValidationError,
    model_validator,
)

from src.schemas.agent_io import NeighborStatus, WeatherContext
from src.schemas.anomaly import Pollutant

KNOWLEDGE_BASE = Path(__file__).resolve().parents[1] / "data" / "knowledge_base"

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
WindDirection = Literal[
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
]


class KnowledgeWeatherContext(WeatherContext):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    temperature_c: float | None = Field(default=None, ge=-273.15)
    wind_speed_kmh: float | None = Field(default=None, ge=0)
    wind_direction: WindDirection | None = None
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    conditions: NonEmptyText | None = None


class KnowledgeNeighborStatus(NeighborStatus):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    station_id: NonEmptyText
    station_name: NonEmptyText
    distance_km: float = Field(ge=0)
    value: float = Field(ge=0)


class ObservedArea(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: NonEmptyText
    observation_type: Literal[
        "surface_increase", "reported_unaffected", "plume_observed", "monitoring_area"
    ]


class DocumentedMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    value: float
    unit: Literal["%", "µg/m³", "mg/m³", "ppb", "ppbv", "ppm", "ppmv"]
    quantity: Literal["concentration", "relative_change"]
    operator: Literal["equal", "greater_than"] = "equal"
    averaging_minutes: int | None = Field(default=None, gt=0)
    aggregation_period: NonEmptyText | None = None
    statistic: NonEmptyText

    @model_validator(mode="after")
    def validate_measurement(self) -> "DocumentedMeasurement":
        if self.averaging_minutes is None and self.aggregation_period is None:
            raise ValueError("Measurements require an averaging interval or aggregation period")
        if (self.quantity == "relative_change") != (self.unit == "%"):
            raise ValueError("Relative changes must use percent units")
        if self.quantity == "concentration" and self.value < 0:
            raise ValueError("Concentration cannot be negative")
        return self


class DocumentedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pollutant: Pollutant
    direction: Literal["increase", "decrease"]
    area: NonEmptyText | None = None
    station_name: NonEmptyText | None = None
    comparison: NonEmptyText | None = None
    measurement: DocumentedMeasurement | None = None

    @model_validator(mode="after")
    def validate_relative_change(self) -> "DocumentedChange":
        measurement = self.measurement
        if measurement is None or measurement.quantity != "relative_change":
            return self
        if self.comparison is None:
            raise ValueError("Relative changes require a comparison baseline")
        if measurement.operator != "equal":
            raise ValueError("Relative changes must be reported as exact values")
        value = measurement.value
        if (self.direction == "increase" and value <= 0) or (
            self.direction == "decrease" and value >= 0
        ):
            raise ValueError("Relative change value must agree with direction")
        return self


class SourceLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    description: NonEmptyText
    source_url: HttpUrl


class KnowledgeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    kind: Literal["pollution_source", "historical_event"]
    category: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    title: NonEmptyText
    country: str = Field(pattern=r"^[A-Z]{2}$")
    region: NonEmptyText
    pollutants: list[Pollutant] = Field(min_length=1)
    start_date: date | None = None
    end_date: date | None = None
    summary: NonEmptyText
    investigation_hint: NonEmptyText
    expected_signals: list[NonEmptyText] = Field(min_length=1)
    contradicting_signals: list[NonEmptyText] = Field(min_length=1)
    required_context: list[NonEmptyText] = Field(min_length=1)
    evidence_type: Literal[
        "emissions_inventory",
        "ground_monitoring",
        "satellite_observation",
        "ground_monitoring_and_remote_sensing",
    ]
    source_url: HttpUrl
    source_location: SourceLocation | None = None
    observed_areas: list[ObservedArea] | None = Field(default=None, min_length=1)
    temporal_pattern: NonEmptyText | None = None
    documented_changes: list[DocumentedChange] | None = Field(default=None, min_length=1)
    weather_context: KnowledgeWeatherContext | None = None
    neighbors: list[KnowledgeNeighborStatus] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_dates_and_pollutants(self) -> "KnowledgeRecord":
        if len(set(self.pollutants)) != len(self.pollutants):
            raise ValueError("Pollutant tags must be unique")
        for change in self.documented_changes or []:
            if change.pollutant not in self.pollutants:
                raise ValueError("Documented changes must use a pollutant tagged in the record")
        if self.weather_context is not None and not self.weather_context.model_dump(
            exclude_none=True
        ):
            raise ValueError("Weather context must include at least one observation")
        station_ids = [neighbor.station_id for neighbor in self.neighbors or []]
        if len(station_ids) != len(set(station_ids)):
            raise ValueError("Neighbor station IDs must be unique")
        if self.kind == "historical_event":
            if self.source_location is not None:
                raise ValueError("Source locations are reserved for pollution source records")
            if self.start_date is None or self.end_date is None:
                raise ValueError("Historical events require both dates")
            if self.start_date > self.end_date:
                raise ValueError("Start date must be on or before end date")
        elif {"start_date", "end_date"} & self.model_fields_set:
            raise ValueError("Pollution source records must omit event dates")
        return self


def build_knowledge_base(source: Path, output: Path) -> list[KnowledgeRecord]:
    records: list[KnowledgeRecord] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(source.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            record = KnowledgeRecord.model_validate_json(line, strict=True)
        except ValidationError as exc:
            raise ValueError(f"{source}:{line_number}: {exc}") from exc
        if record.id in seen_ids:
            raise ValueError(f"{source}:{line_number}: duplicate record ID {record.id!r}")
        seen_ids.add(record.id)
        records.append(record)

    if not records:
        raise ValueError(f"{source}: expected at least one record")

    payload = ",\n".join(f"  {record.model_dump_json(exclude_none=True)}" for record in records)
    with TemporaryDirectory(dir=output.parent) as staging_directory:
        staged = Path(staging_directory) / output.name
        staged.write_text(
            f"[\n{payload}\n]\n",
            encoding="utf-8",
            newline="\n",
        )
        staged.replace(output)
    return records


def main() -> None:
    source = KNOWLEDGE_BASE / "research" / "knowledge_base_verified.jsonl"
    output = KNOWLEDGE_BASE / "air_pollution_cases.json"
    try:
        records = build_knowledge_base(source, output)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    tags = sorted({pollutant.value for record in records for pollutant in record.pollutants})
    print(f"Wrote {len(records)} records to {output}")
    print(f"Pollutant tags: {', '.join(tags)}")


if __name__ == "__main__":
    main()
