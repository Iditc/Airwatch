# AirWatch pollution knowledge base

AirWatch maintains two collections. Historical cases cover past pollution
events and documented emission sources. Mechanism research covers reusable
explanations, measurement limitations, and checks for investigating new events.

The input datasets, generated JSON exports, and research reports are stored
outside Git. Place your local copies at the paths below before running a
builder. The unit tests use synthetic records and run without these datasets.

## Mechanism research

From the repository root, run:

```shell
python -m scripts.build_mechanism_knowledge_base
```

Place the Task 2 JSONL baseline in `research/air_pollution_mechanisms` and
the Task 3 follow-up JSONL files in `research/air_pollution_mechanisms_followup`,
under `data/knowledge_base`. The builder validates both batches. It
applies documented replacements by mechanism ID and rebuilds the source links.
The four `air_pollution_mechanism*.json` and `air_pollution_diagnostic*.json`
exports contain mechanisms, sources, diagnostic checks, and required inputs.
Research summaries and update logs document verification and unresolved gaps.

## Historical cases

`research/knowledge_base_verified.jsonl` is the active input for the first phase. It
contains one JSON object per line. Keep partially verified and unverified
records in their respective JSONL files for later review. Run the generator
from the repository root.

```shell
python -m scripts.build_historical_knowledge_base
```

The generator validates the active input and writes `air_pollution_cases.json`,
the JSON array for the Chroma index in issue #8. Edit the active JSONL file to
update the generated output. Validation errors include the source line number
when they apply to a particular record. The local `research/records.jsonl`
preserves the original research baseline.

Use compass abbreviations such as `E` or `NNW` for documented wind direction.
Use signed percentages with a comparison baseline for relative changes and
concentration units such as `µg/m³` or `ppb` for concentration measurements.

| Field | Purpose |
| --- | --- |
| `id` | Stable ID for Chroma upserts and citations. Keep it when revising a record. |
| `kind` | `pollution_source` for a source or recurring mechanism, `historical_event` for a dated episode. |
| `category` | Lowercase, underscore-separated label for the emission or transport mechanism. |
| `country` | Required uppercase ISO 3166-1 alpha-2 code, such as `IL` or `US`. For cross-border events, use the country of the primary documented observation and describe the broader footprint in `observed_areas`. |
| `title`, `region`, `summary` | Searchable description of the documented evidence and its location. |
| `pollutants` | Retrieval tags using the values in `src.schemas.anomaly.Pollutant`. |
| `start_date`, `end_date` | Inclusive ISO dates for the documented episode or observation window. Omit both for source records. |
| `investigation_hint` | Checks the agent can apply to the current anomaly. |
| `expected_signals` | Observations that would support the hypothesis. |
| `contradicting_signals` | Observations that would weaken the hypothesis. |
| `required_context` | Current-event data needed to assess the signals. |
| `evidence_type` | How the cited evidence was obtained, such as ground monitoring or an emissions inventory. |
| `source_url` | Primary reference for the documented evidence. |
| `observed_areas` | Documented area names and observation types. Omit areas the source does not cover. |
| `temporal_pattern` | Documented time of day, duration, or recurrence of a change. |
| `documented_changes` | Pollutant, direction, and optional area, station name, and comparison. Numeric observations specify quantity, operator, value, unit, averaging interval or aggregation period, and statistic. |
| `source_location` | Documented source coordinates, their scope, and a separate reference for the location. |
| `weather_context` | Documented weather using the shared `WeatherContext` model. |
| `neighbors` | Optional station comparisons using `NeighborStatus` when a reference station and all required details are documented. For historical measurements at a named station, use `documented_changes.station_name`. |

## Indexing in issue #8

- Create one LangChain document per record. Use the title, region, pollutant
  tags, summary, investigation hint, and signal lists as labeled sections of the text to embed.
  Include the required context when presenting the retrieved record to the agent.
  Include documented areas, temporal patterns, and pollutant changes when available.
- Use the record ID as the Chroma ID. Keep `kind`, `category`, `country`, `region`, `evidence_type`, and
  `source_url` as scalar metadata. For pollutant filtering, derive one Boolean
  metadata field per pollutant, such as `has_pm10`. Include the date strings in
  metadata for historical events.
- Retrieve historical events as analogues across years. Use their dates to
  describe when the evidence was observed. For a new event, compare current
  weather and station readings with the retrieved record before attributing a cause.
- In `RootCauseAnalysis`, use the retrieved record ID in `known_source_match`
  for a pollution source and in `historical_match` for a similar historical event.

Pollutant tags indicate search relevance. For example, sulfur oxide inventory
data is useful context for an SO2 query, and satellite smoke imagery is useful
context for a PM2.5 query. Surface concentrations require station measurements.
The signal lists describe checks for a new anomaly. Missing measurements leave
those checks unresolved.

## CO and ozone measurement references

- [National station catalog](https://data.gov.il/he/datasets/ministry_of_the_environment/air-stations)
  lists station locations and measured pollutants. Use it to find CO and ozone monitors.
- [Annual station data](https://www.gov.il/he/departments/dynamiccollectors/monitoring-stations)
  and the [national monitoring portal](https://air.sviva.gov.il/) are starting points
  for station observations. Check availability, units, and averaging intervals.
- [Tel Aviv-Yafo and Gush Dan 2011 monitoring report](https://www.tel-aviv.gov.il/Forms/%D7%93%D7%95%D7%97%20%D7%A0%D7%99%D7%98%D7%95%D7%A8%20%D7%90%D7%95%D7%95%D7%99%D7%A8%20%D7%9C%D7%A9%D7%A0%D7%AA%202011.pdf)
  summarizes historical CO and ozone levels and reports no exceedances for
  either pollutant in 2011 under the standards used in the report.
