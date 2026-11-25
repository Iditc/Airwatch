"""Input and result models for AirWatch knowledge base retrieval."""

from datetime import date, timezone
from itertools import pairwise
from math import isfinite
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    PositiveInt,
    StringConstraints,
    field_validator,
)

from src.schemas.agent_io import NeighborStatus, WeatherContext
from src.schemas.anomaly import AnomalyEvent, Pollutant

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ReviewStatus = Literal["verified", "partially_verified", "unverified"]
EvidenceBasis = Literal["reported_finding", "synthesis"]


class RecentMeasurement(BaseModel):
    """One reported concentration in a station's measurement series."""

    timestamp: AwareDatetime = Field(
        description="Observation time, or end of the averaging period for averaged readings."
    )
    value: FiniteFloat
    quality_flag: NonEmptyText | None = None


class StationMeasurementSeries(BaseModel):
    """Comparable readings for one station and pollutant."""

    station_id: NonEmptyText
    pollutant: Pollutant
    unit: NonEmptyText
    averaging_period_seconds: PositiveInt | None = Field(
        default=None,
        description="Averaging period in seconds, when known and applicable.",
    )
    measurements: list[RecentMeasurement] = Field(
        min_length=1, description="Measurements in strictly increasing timestamp order."
    )

    @field_validator("measurements")
    @classmethod
    def validate_timestamp_order(
        cls, measurements: list[RecentMeasurement]
    ) -> list[RecentMeasurement]:
        times = (point.timestamp.astimezone(timezone.utc) for point in measurements)
        if any(previous >= current for previous, current in pairwise(times)):
            raise ValueError("Measurement timestamps must be strictly increasing")
        return measurements


class KnowledgeRetrievalRequest(BaseModel):
    """Observed event context used to retrieve candidate explanations."""

    model_config = ConfigDict(extra="forbid")

    event: AnomalyEvent
    region: NonEmptyText | None = None
    measurement_unit: NonEmptyText | None = None
    weather: WeatherContext | None = None
    neighbors: list[NeighborStatus] | None = Field(
        default=None,
        description=(
            "Caller-provided comparisons for the event pollutant and a comparable "
            "time window. None means neighbor observations were not supplied."
        ),
    )
    recent_measurement_series: list[StationMeasurementSeries] | None = Field(
        default=None,
        description=(
            "Recent readings available at analysis time. The event station is identified "
            "by event.station_id. Other series describe comparison stations."
        ),
    )

    @field_validator("event")
    @classmethod
    def validate_event_measurements(cls, event: AnomalyEvent) -> AnomalyEvent:
        if not (isfinite(event.value) and isfinite(event.baseline_value)):
            raise ValueError("Event measurement and baseline must be finite")
        return event


class HistoricalKnowledgeMatch(BaseModel):
    """A dated analogue or a documented emission source from the historical collection."""

    record_id: NonEmptyText
    kind: Literal["historical_event", "pollution_source"]
    title: NonEmptyText
    region: NonEmptyText
    pollutants: list[Pollutant] = Field(min_length=1)
    summary: NonEmptyText
    source_url: NonEmptyText
    start_date: date | None = None
    end_date: date | None = None
    investigation_hint: NonEmptyText
    expected_signals: list[NonEmptyText] = Field(default_factory=list)
    contradicting_signals: list[NonEmptyText] = Field(default_factory=list)
    required_context: list[NonEmptyText] = Field(default_factory=list)
    matched_on: list[NonEmptyText] = Field(default_factory=list)


class RetrievedEvidence(BaseModel):
    """An individual claim with the information needed to cite its source."""

    evidence_id: NonEmptyText
    claim: NonEmptyText
    source_id: NonEmptyText
    source_title: NonEmptyText
    source_url: NonEmptyText
    locator: NonEmptyText
    verification_status: ReviewStatus
    verification_note: NonEmptyText


class EventInputStatus(BaseModel):
    """Availability of a required observation for this particular event."""

    name: NonEmptyText
    status: Literal["available", "missing", "unknown"]
    detail: NonEmptyText | None = None


class DiagnosticInputStatus(EventInputStatus):
    """An event input linked to the diagnostic input inventory."""

    input_id: NonEmptyText
    documentation_url: NonEmptyText | None = None


class DiagnosticInterpretation(BaseModel):
    """Possible interpretations supported by evidence local to the diagnostic check."""

    explanation: NonEmptyText
    supports: NonEmptyText | None = None
    weakens: NonEmptyText | None = None
    basis: EvidenceBasis
    evidence_ids: list[NonEmptyText] = Field(min_length=1)


class RetrievedDiagnosticCheck(BaseModel):
    """A diagnostic procedure and the evidence needed to interpret its results."""

    check_id: NonEmptyText
    title: NonEmptyText
    trigger_pattern: NonEmptyText
    procedure: list[NonEmptyText] = Field(min_length=1)
    interpretations: list[DiagnosticInterpretation] = Field(min_length=1)
    inconclusive_when: list[NonEmptyText] = Field(default_factory=list)
    limitations: list[NonEmptyText] = Field(default_factory=list)
    required_inputs: list[DiagnosticInputStatus] = Field(default_factory=list)
    evidence: list[RetrievedEvidence] = Field(min_length=1)
    review_status: ReviewStatus


class MechanismSignal(BaseModel):
    """A supporting or weakening observation linked to the mechanism's evidence."""

    observation: NonEmptyText
    basis: EvidenceBasis
    evidence_ids: list[NonEmptyText] = Field(default_factory=list)


class MechanismApplicability(BaseModel):
    geographic_scope: Literal["global", "regional", "country_specific", "site_specific"]
    countries: list[NonEmptyText] = Field(default_factory=list)
    regions: list[NonEmptyText] = Field(default_factory=list)
    seasons: list[NonEmptyText] = Field(default_factory=list)
    station_types: list[NonEmptyText] = Field(default_factory=list)
    instrument_scope: NonEmptyText | None = None
    transfer_limitations: list[NonEmptyText] = Field(default_factory=list)


class MechanismKnowledgeMatch(BaseModel):
    """A reusable mechanism with research evidence and related diagnostic checks."""

    record_id: NonEmptyText
    title: NonEmptyText
    topic: NonEmptyText
    pollutants: list[Pollutant] = Field(min_length=1)
    summary: NonEmptyText
    mechanism_explanation: NonEmptyText
    applicability: MechanismApplicability
    review_status: ReviewStatus
    expected_signals: list[MechanismSignal] = Field(default_factory=list)
    contradicting_signals: list[MechanismSignal] = Field(default_factory=list)
    required_context: list[EventInputStatus] = Field(default_factory=list)
    limitations: list[NonEmptyText] = Field(default_factory=list)
    evidence: list[RetrievedEvidence] = Field(min_length=1)
    diagnostic_checks: list[RetrievedDiagnosticCheck] = Field(default_factory=list)
    matched_on: list[NonEmptyText] = Field(default_factory=list)


class KnowledgeRetrievalResult(BaseModel):
    """Ordered retrieval results for one event, ready to pass to the analysis layer."""

    model_config = ConfigDict(extra="forbid")

    event_id: NonEmptyText
    historical_matches: list[HistoricalKnowledgeMatch] = Field(default_factory=list)
    mechanism_matches: list[MechanismKnowledgeMatch] = Field(default_factory=list)
