-- SQLite schema for the local AirWatch knowledge base.
-- Initialize a new database with this script. Enable foreign_keys on every
-- connection that writes to it. Event observations arrive with retrieval requests.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE import_manifest (
    file_name TEXT NOT NULL PRIMARY KEY,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    record_count INTEGER NOT NULL CHECK (typeof(record_count) = 'integer' AND record_count >= 0)
);

CREATE TABLE pollutants (
    code TEXT NOT NULL PRIMARY KEY
);

INSERT INTO pollutants (code) VALUES ('pm25'), ('pm10'), ('no2'), ('so2'), ('co'), ('o3');

-- The JSON payload is the complete validated export record. Columns and link
-- tables expose the fields needed for filtering and joins.
CREATE TABLE historical_records (
    id TEXT NOT NULL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('historical_event', 'pollution_source')),
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    country TEXT NOT NULL,
    region TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    source_url TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object'),
    CHECK (
        (kind = 'historical_event' AND start_date IS NOT NULL AND end_date IS NOT NULL
         AND start_date <= end_date)
        OR (kind = 'pollution_source' AND start_date IS NULL AND end_date IS NULL)
    )
);

CREATE TABLE historical_record_pollutants (
    historical_record_id TEXT NOT NULL REFERENCES historical_records(id) ON DELETE CASCADE,
    pollutant TEXT NOT NULL REFERENCES pollutants(code),
    PRIMARY KEY (historical_record_id, pollutant)
);

CREATE TABLE mechanisms (
    id TEXT NOT NULL PRIMARY KEY,
    title TEXT NOT NULL,
    topic TEXT NOT NULL CHECK (
        topic IN ('emissions', 'atmospheric_chemistry', 'meteorology', 'transport', 'measurement_quality')
    ),
    geographic_scope TEXT NOT NULL CHECK (
        geographic_scope IN ('global', 'regional', 'country_specific', 'site_specific')
    ),
    review_status TEXT NOT NULL CHECK (
        review_status IN ('verified', 'partially_verified', 'unverified')
    ),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object')
);

CREATE TABLE mechanism_pollutants (
    mechanism_id TEXT NOT NULL REFERENCES mechanisms(id) ON DELETE CASCADE,
    pollutant TEXT NOT NULL REFERENCES pollutants(code),
    PRIMARY KEY (mechanism_id, pollutant)
);

CREATE TABLE research_sources (
    source_id TEXT NOT NULL PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    doi TEXT,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object')
);

-- Evidence IDs are local to their parent. The source relationship is carried
-- by the evidence so a source can support several claims in one mechanism.
CREATE TABLE mechanism_evidence (
    mechanism_id TEXT NOT NULL REFERENCES mechanisms(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES research_sources(source_id),
    claim TEXT NOT NULL,
    locator TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('verified', 'partially_verified', 'unverified')
    ),
    verification_note TEXT NOT NULL,
    PRIMARY KEY (mechanism_id, evidence_id)
);

CREATE TABLE diagnostic_checks (
    id TEXT NOT NULL PRIMARY KEY,
    title TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK (
        review_status IN ('verified', 'partially_verified', 'unverified')
    ),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object')
);

CREATE TABLE diagnostic_check_pollutants (
    check_id TEXT NOT NULL REFERENCES diagnostic_checks(id) ON DELETE CASCADE,
    pollutant TEXT NOT NULL REFERENCES pollutants(code),
    PRIMARY KEY (check_id, pollutant)
);

CREATE TABLE mechanism_diagnostic_checks (
    mechanism_id TEXT NOT NULL REFERENCES mechanisms(id) ON DELETE CASCADE,
    check_id TEXT NOT NULL REFERENCES diagnostic_checks(id) ON DELETE CASCADE,
    PRIMARY KEY (mechanism_id, check_id)
);

CREATE TABLE diagnostic_check_evidence (
    check_id TEXT NOT NULL REFERENCES diagnostic_checks(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES research_sources(source_id),
    claim TEXT NOT NULL,
    locator TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('verified', 'partially_verified', 'unverified')
    ),
    verification_note TEXT NOT NULL,
    PRIMARY KEY (check_id, evidence_id)
);

CREATE TABLE diagnostic_inputs (
    id TEXT NOT NULL PRIMARY KEY,
    name TEXT NOT NULL,
    schema_availability TEXT NOT NULL CHECK (
        schema_availability IN ('direct', 'derived', 'additional_data_required', 'unknown')
    ),
    availability_at_event_time TEXT NOT NULL CHECK (
        availability_at_event_time IN ('real_time', 'near_real_time', 'retrospective', 'unknown')
    ),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object')
);

CREATE TABLE diagnostic_check_inputs (
    check_id TEXT NOT NULL REFERENCES diagnostic_checks(id) ON DELETE CASCADE,
    input_id TEXT NOT NULL REFERENCES diagnostic_inputs(id),
    PRIMARY KEY (check_id, input_id)
);

CREATE TABLE diagnostic_input_sources (
    input_id TEXT NOT NULL REFERENCES diagnostic_inputs(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES research_sources(source_id),
    PRIMARY KEY (input_id, source_id)
);

CREATE INDEX historical_records_by_location
    ON historical_records (country, region, kind, start_date);
CREATE INDEX historical_records_by_pollutant
    ON historical_record_pollutants (pollutant, historical_record_id);
CREATE INDEX mechanisms_by_pollutant ON mechanism_pollutants (pollutant, mechanism_id);
CREATE INDEX diagnostic_checks_by_pollutant ON diagnostic_check_pollutants (pollutant, check_id);

CREATE INDEX mechanism_evidence_by_source ON mechanism_evidence (source_id);
CREATE INDEX mechanism_links_by_check ON mechanism_diagnostic_checks (check_id);
CREATE INDEX diagnostic_evidence_by_source ON diagnostic_check_evidence (source_id);
CREATE INDEX diagnostic_checks_by_input ON diagnostic_check_inputs (input_id);
CREATE INDEX diagnostic_inputs_by_source ON diagnostic_input_sources (source_id);

PRAGMA user_version = 1;
COMMIT;
