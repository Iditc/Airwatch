#!/usr/bin/env python3
"""Validate the Task 3 research schema, references, and consistency with Task 2.
Usage: python -m scripts.validate_task3_mechanism_research [task3_dir] [task2_dir]."""

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.validate_task2_mechanism_research import ABSTRACT_ONLY, BODY_LOC, LOC_RE, emb

RESEARCH = Path(__file__).resolve().parents[1] / "data/knowledge_base/research"
D3 = Path(sys.argv[1]) if len(sys.argv) > 1 else RESEARCH / "air_pollution_mechanisms_followup"
D2 = Path(sys.argv[2] if len(sys.argv) > 2 else D3.parent / "air_pollution_mechanisms")


ERR: list[str] = []
err = ERR.append
TOPICS = {"emissions", "atmospheric_chemistry", "meteorology", "transport", "measurement_quality"}
POLS = {"pm25", "pm10", "no2", "so2", "co", "o3"}
REVIEW = {"verified", "partially_verified", "unverified"}
BASIS = {"reported_finding", "synthesis"}
EVT = {
    "field_observation",
    "controlled_experiment",
    "modeling",
    "review_synthesis",
    "technical_guidance",
}  # Task 2 spec enum (no official_assessment)
STYPES = {"original_research", "review", "official_assessment", "technical_guidance"}
ACCESS = {"full_text", "abstract_only", "metadata_only"}
GEO = {"global", "regional", "country_specific", "site_specific"}
SA = {"direct", "derived", "additional_data_required", "unknown"}
AV = {"real_time", "near_real_time", "retrospective", "unknown"}
ASSESS = {"strengthened", "narrowed", "contradicted", "confirmed", "unresolved"}
T2FIELDS = {
    "station_id",
    "station_name",
    "latitude",
    "longitude",
    "timestamp",
    "pollutant",
    "measured_value",
    "baseline_value",
    "anomaly_score",
    "severity",
    "temperature",
    "wind_speed",
    "wind_direction",
    "humidity",
    "weather_conditions",
    "neighboring_station_values",
    "neighboring_station_distances",
    "neighboring_station_anomaly_flags",
}
CTX_TRUE_OK = T2FIELDS | {"station_id_and_name"}
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MK = [
    "id",
    "title",
    "topic",
    "pollutants",
    "summary",
    "mechanism_explanation",
    "applicability",
    "expected_signals",
    "contradicting_signals",
    "required_context",
    "alternative_explanations",
    "temporal_pattern",
    "spatial_pattern",
    "limitations",
    "evidence",
    "source_ids",
    "review_status",
    "quantitative_findings",
    "embedding_text",
]
APK = {
    "geographic_scope",
    "countries",
    "regions",
    "seasons",
    "station_types",
    "instrument_scope",
    "transfer_limitations",
}
EK = {
    "id",
    "claim",
    "source_id",
    "locator",
    "evidence_type",
    "verification_status",
    "verification_note",
}
QK = {
    "pollutant",
    "finding",
    "value",
    "unit",
    "statistic",
    "averaging_period",
    "comparison_baseline",
    "scope",
    "evidence_id",
}
SK = {
    "source_id",
    "title",
    "authors_or_organization",
    "publisher",
    "publication_date",
    "source_type",
    "url",
    "doi",
    "language",
    "access_level",
    "accessed_on",
    "record_ids",
    "verification_notes",
}
CK = {
    "id",
    "title",
    "mechanism_ids",
    "pollutants",
    "trigger_pattern",
    "input_ids",
    "procedure",
    "interpretations",
    "inconclusive_when",
    "applicability",
    "limitations",
    "evidence",
    "review_status",
}
IK = {
    "id",
    "name",
    "description",
    "schema_availability",
    "schema_fields",
    "derivation",
    "provider",
    "documentation_url",
    "coverage",
    "time_resolution",
    "spatial_resolution",
    "units",
    "availability_at_event_time",
    "publication_latency",
    "access_requirements",
    "availability_verified_on",
    "availability_verification",
    "limitations",
    "source_ids",
}
I_NULLABLE = {
    "derivation",
    "provider",
    "documentation_url",
    "coverage",
    "time_resolution",
    "spatial_resolution",
    "publication_latency",
    "availability_verified_on",
}
UK = {
    "record_id",
    "assessment",
    "previous_review_status",
    "proposed_review_status",
    "changed_fields",
    "rationale",
    "source_ids",
    "replacement_in_batch",
}
NOT_AVAIL_CTX = re.compile(
    r"time_series|mixing_layer|boundary|instrument|station_type|operator|trajector|stack|calibration|status_flags|co_located|raw_5min|solar|fire|traffic|calendar|altitude|units|timestamp_convention|history|model|satellite",
    re.I,
)


def strict_load(p: Path) -> list[dict[str, Any]]:
    rows = []
    text = p.read_text(encoding="utf-8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if len(lines) >= 300:
        err(f"{p.name}: {len(lines)} lines (limit <300)")

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        ks = [k for k, _ in pairs]
        d = [k for k, c in Counter(ks).items() if c > 1]
        if d:
            raise ValueError(f"duplicate keys {d}")
        return dict(pairs)

    def bad_const(c: str) -> None:
        raise ValueError(f"non-finite number {c}")

    for i, line in enumerate(lines, 1):
        if not line.strip():
            err(f"{p.name}:{i} blank line")
            continue
        try:
            o = json.loads(line, object_pairs_hook=hook, parse_constant=bad_const)
        except Exception as e:
            err(f"{p.name}:{i} invalid JSON: {e}")
            continue
        if not isinstance(o, dict):
            err(f"{p.name}:{i} not an object")
            continue
        rows.append(o)
    return rows


def load_set(pattern: str, d: Path = D3) -> list[dict[str, Any]]:
    out = []
    for p in sorted(d.glob(pattern)):
        out += strict_load(p)
    return out


def keys_exact(o: dict[str, Any], ks: list[str] | set[str], where: str) -> None:
    if set(o) != set(ks):
        err(
            f"{where}: keys mismatch missing={sorted(set(ks) - set(o))} "
            f"extra={sorted(set(o) - set(ks))}"
        )


def uniq(ids: list[Any], what: str) -> None:
    for k, c in Counter(ids).items():
        if c > 1:
            err(f"duplicate {what} id {k}")
    for k in ids:
        if not isinstance(k, str) or not ID_RE.match(k):
            err(f"{what} id not lowercase-hyphenated: {k!r}")


def nums_in(v: Any) -> set[str]:
    c = {repr(v), str(v)}
    if isinstance(v, float) and v.is_integer():
        c.add(str(int(v)))
    if isinstance(v, int | float) and v < 0:
        c |= {str(abs(v)), "−" + str(abs(v))}
    return c


def check_evidence(
    ev: list[dict[str, Any]], where: str, srcmap: dict[str, dict[str, Any]]
) -> set[Any]:
    ids = []
    for e in ev:
        keys_exact(e, EK, f"{where} evidence {e.get('id')}")
        ids.append(e.get("id"))
        if e.get("evidence_type") not in EVT:
            err(
                f"{where} {e.get('id')}: evidence_type {e.get('evidence_type')!r}"
                " not in Task 2 evidence enum"
            )
        if e.get("verification_status") not in REVIEW:
            err(f"{where} {e.get('id')}: bad verification_status")
        s = srcmap.get(e.get("source_id", ""))
        if s is None:
            err(f"{where} {e.get('id')}: source {e.get('source_id')} not in Task 3 inventory")
            continue
        locator = e.get("locator") or ""
        if e.get("verification_status") == "verified":
            if not LOC_RE.search(locator) and not re.search(
                r"(section|Sect\.|Appendix|Annex|FAQ|catalogue entry)", locator, re.I
            ):
                err(f"{where} {e['id']}: verified without precise locator {locator!r}")
            if ABSTRACT_ONLY.search(locator) and not BODY_LOC.search(locator):
                err(f"{where} {e['id']}: verified on abstract-only locator")
            if locator.lower().startswith("homepage") or "landing page" in locator.lower():
                err(f"{where} {e['id']}: verified on homepage/landing page")
            if s["access_level"] != "full_text":
                err(f"{where} {e['id']}: verified but source access_level={s['access_level']}")
        if not e.get("verification_note"):
            err(f"{where} {e.get('id')}: empty verification_note")
    if len(ids) != len(set(ids)):
        err(f"{where}: duplicate local evidence ids")
    return set(ids)


def rollup(status: str, ev: list[dict[str, Any]], where: str) -> None:
    st = {e.get("verification_status") for e in ev}
    if status == "verified" and st != {"verified"}:
        err(f"{where}: verified but evidence statuses {st}")
    if status == "partially_verified" and "verified" not in st and "partially_verified" not in st:
        err(f"{where}: partial with no supporting evidence")


def main() -> int:
    t2recs = {r["id"]: r for r in load_set("air_pollution_mechanisms_*.jsonl", D2)}
    t2src = {s["source_id"]: s for s in strict_load(D2 / "source_inventory.jsonl")}
    ERR.clear()  # Task 2 parsing issues are not Task 3 errors
    mechs = load_set("air_pollution_mechanisms_*.jsonl")
    inv = load_set("source_inventory*.jsonl")
    checks = load_set("diagnostic_checks_*.jsonl")
    inputs = load_set("data_inputs_*.jsonl")
    ups = load_set("record_updates_*.jsonl")
    for p in list(D3.glob("*.md")) + list(D3.glob("*.py")):
        n = len(p.read_text(encoding="utf-8").splitlines())
        if n >= 300:
            err(f"{p.name}: {n} lines (limit <300)")
    uniq([m.get("id") for m in mechs], "mechanism")
    uniq([s.get("source_id") for s in inv], "source")
    uniq([c.get("id") for c in checks], "check")
    uniq([d.get("id") for d in inputs], "input")
    uniq([u.get("record_id") for u in ups], "update")
    srcmap = {s["source_id"]: s for s in inv}
    upmap = {u["record_id"]: u for u in ups}
    inmap = {d["id"]: d for d in inputs}
    allmech = set(t2recs) | {m["id"] for m in mechs}
    # sources
    for s in inv:
        keys_exact(s, SK, f"source {s.get('source_id')}")
        if s.get("source_type") not in STYPES:
            err(f"{s['source_id']}: bad source_type")
        if s.get("access_level") not in ACCESS:
            err(f"{s['source_id']}: bad access_level")
        if not re.match(r"^(\d{4}(-\d{2}(-\d{2})?)?|undated)$", str(s.get("publication_date"))):
            err(f"{s['source_id']}: bad publication_date")
        if not DATE_RE.match(str(s.get("accessed_on"))):
            err(f"{s['source_id']}: bad accessed_on")
        if s["source_id"] in t2src:
            o = t2src[s["source_id"]]
            if (
                (o.get("doi") or "").lower() != (s.get("doi") or "").lower()
                or o["url"] != s["url"]
                or o["title"] != s["title"]
            ):
                err(f"{s['source_id']}: reused Task 2 source id but publication identity differs")
        else:
            for o in t2src.values():
                if (s.get("doi") and o.get("doi") and s["doi"].lower() == o["doi"].lower()) or s[
                    "url"
                ] == o["url"]:
                    err(f"{s['source_id']}: same publication as Task 2 {o['source_id']} but new id")
    dois = [s["doi"].lower() for s in inv if s.get("doi")]
    [err(f"duplicate DOI {d}") for d, c in Counter(dois).items() if c > 1]
    # mechanisms
    cites: dict[str, set[str]] = {}
    for m in mechs:
        w = f"mech {m.get('id')}"
        keys_exact(m, MK, w)
        if m["id"] in t2recs and not (m["id"] in upmap and upmap[m["id"]]["replacement_in_batch"]):
            err(f"{w}: collides with Task 2 id without declared replacement")
        if m.get("topic") not in TOPICS:
            err(f"{w}: bad topic")
        if not m["pollutants"] or set(m["pollutants"]) - POLS:
            err(f"{w}: bad pollutants")
        if m.get("review_status") not in REVIEW:
            err(f"{w}: bad review_status")
        keys_exact(m["applicability"], APK, f"{w} applicability")
        if m["applicability"].get("geographic_scope") not in GEO:
            err(f"{w}: bad geographic_scope")
        eids = check_evidence(m["evidence"], w, srcmap)
        rollup(m["review_status"], m["evidence"], w)
        if not m["evidence"]:
            err(f"{w}: no evidence")
        for s in m["expected_signals"] + m["contradicting_signals"]:
            if set(s) != {"observation", "evidence_ids", "basis"} or s.get("basis") not in BASIS:
                err(f"{w}: bad signal {s}")
            for e in s.get("evidence_ids", []):
                if e not in eids:
                    err(f"{w}: signal evidence {e} unresolved")
            if s.get("basis") == "reported_finding" and not s.get("evidence_ids"):
                err(f"{w}: reported_finding signal without evidence")
        exp = {s["observation"].strip().lower() for s in m["expected_signals"]}
        con = {s["observation"].strip().lower() for s in m["contradicting_signals"]}
        if exp & con:
            err(f"{w}: observation both supporting and contradicting")
        for rc in m["required_context"]:
            if set(rc) != {"input", "purpose", "available_in_current_schema"} or not isinstance(
                rc["available_in_current_schema"], bool
            ):
                err(f"{w}: bad required_context {rc}")
            elif rc["available_in_current_schema"] and rc["input"] not in CTX_TRUE_OK:
                err(f"{w}: context {rc['input']} marked available but not a Task 2 schema field")
            elif rc["available_in_current_schema"] and NOT_AVAIL_CTX.search(rc["input"]):
                err(f"{w}: context {rc['input']} listed as unavailable in Task 2")
        for a in m["alternative_explanations"]:
            if set(a) != {"explanation", "discriminating_observations"}:
                err(f"{w}: bad alternative")
        claims = {e["id"]: e["claim"] for e in m["evidence"]}
        for q in m["quantitative_findings"]:
            keys_exact(q, QK, f"{w} quantitative")
            v = q.get("value")
            if not isinstance(v, int | float) or isinstance(v, bool) or not math.isfinite(v):
                err(f"{w}: non-numeric value")
                continue
            if q.get("pollutant") not in POLS or not q.get("unit"):
                err(f"{w}: quantitative pollutant/unit")
            if q.get("evidence_id") not in eids:
                err(f"{w}: quantitative evidence unresolved")
                continue
            cand = nums_in(v)
            if q["unit"] == "ratio":
                cand.add(str(int(round(v * 100))) + "%")
            if not any(c in claims[q["evidence_id"]] for c in cand):
                err(f"{w}: value {v} not found in claim {q['evidence_id']}")
        if sorted(m["source_ids"]) != sorted({e["source_id"] for e in m["evidence"]}):
            err(f"{w}: source_ids != evidence sources")
        for source_id in m["source_ids"]:
            cites.setdefault(source_id, set()).add(m["id"])
        if m["embedding_text"] != emb(m):
            err(f"{w}: embedding_text differs from Task 2 emb()")
    for s in inv:
        if set(s["record_ids"]) != cites.get(s["source_id"], set()):
            err(
                f"{s['source_id']}: record_ids {s['record_ids']} != "
                f"citing mechanisms {sorted(cites.get(s['source_id'], set()))}"
            )
    # checks
    used = set(cites)
    for c in checks:
        w = f"check {c.get('id')}"
        keys_exact(c, CK, w)
        for mid in c["mechanism_ids"]:
            if mid not in allmech:
                err(f"{w}: mechanism {mid} unresolved in Task 2 ∪ Task 3")
        if set(c["pollutants"]) - POLS or not c["pollutants"]:
            err(f"{w}: bad pollutants")
        for i in c["input_ids"]:
            if i not in inmap:
                err(f"{w}: input {i} unresolved")
        eids = check_evidence(c["evidence"], w, srcmap)
        rollup(c["review_status"], c["evidence"], w)
        if c.get("review_status") not in REVIEW:
            err(f"{w}: bad review_status")
        if len(c["interpretations"]) < 2:
            err(f"{w}: fewer than two candidate explanations")
        refd = set()
        for it in c["interpretations"]:
            if not set(it) <= {
                "explanation",
                "supports",
                "weakens",
                "basis",
                "evidence_ids",
            } or not {"explanation", "basis", "evidence_ids"} <= set(it):
                err(f"{w}: bad interpretation keys")
            if it.get("basis") not in BASIS:
                err(f"{w}: bad basis")
            if not it.get("evidence_ids"):
                err(f"{w}: interpretation without evidence")
            for e in it.get("evidence_ids", []):
                if e not in eids:
                    err(f"{w}: interpretation evidence {e} unresolved")
                refd.add(e)
            if it.get("supports") and it.get("supports") == it.get("weakens"):
                err(f"{w}: same observation supports and weakens")
        if eids - refd:
            err(f"{w}: evidence never referenced {sorted(eids - refd)}")
        for e in c["evidence"]:
            used.add(e["source_id"])
        if not isinstance(c["procedure"], list) or not c["procedure"]:
            err(f"{w}: empty procedure")
    # inputs
    usedin = set()
    for c in checks:
        usedin |= set(c["input_ids"])
    for d in inputs:
        w = f"input {d.get('id')}"
        keys_exact(d, IK, w)
        for k in IK - I_NULLABLE:
            if d.get(k) is None:
                err(f"{w}: {k} is null but not nullable")
        sa, av = d.get("schema_availability"), d.get("availability_at_event_time")
        if sa not in SA:
            err(f"{w}: bad schema_availability")
        if av not in AV:
            err(f"{w}: bad availability_at_event_time")
        if set(d["schema_fields"]) - T2FIELDS:
            err(
                f"{w}: schema_fields not in Task 2 spec "
                f"{sorted(set(d['schema_fields']) - T2FIELDS)}"
            )
        if sa in ("direct", "derived") and not d["schema_fields"]:
            err(f"{w}: {sa} without schema_fields")
        if sa == "derived" and not d["derivation"]:
            err(f"{w}: derived without derivation")
        if sa not in ("direct", "derived") and d["schema_fields"]:
            err(f"{w}: schema_fields given for {sa}")
        if (
            sa not in ("direct", "derived")
            and av in ("real_time", "near_real_time")
            and (not d["availability_verified_on"] or not d["source_ids"])
        ):
            err(f"{w}: real-time claim lacks verification date/sources")
        if d["availability_verified_on"] is not None and not DATE_RE.match(
            d["availability_verified_on"]
        ):
            err(f"{w}: bad date")
        for source_id in d["source_ids"]:
            if source_id not in srcmap:
                err(f"{w}: source {source_id} unresolved")
            used.add(source_id)
        if d["id"] not in usedin:
            err(f"{w}: not used by any check")
    # updates
    repl = {m["id"] for m in mechs if m["id"] in t2recs}
    for u in ups:
        w = f"update {u.get('record_id')}"
        keys_exact(u, UK, w)
        r = u["record_id"]
        if r not in t2recs:
            err(f"{w}: not a Task 2 record")
            continue
        if u["assessment"] not in ASSESS:
            err(f"{w}: bad assessment")
        if u["previous_review_status"] != t2recs[r]["review_status"]:
            err(f"{w}: previous_review_status mismatch")
        if u["proposed_review_status"] not in REVIEW or not isinstance(
            u["replacement_in_batch"], bool
        ):
            err(f"{w}: bad status/boolean")
        for source_id in u["source_ids"]:
            if source_id not in srcmap:
                err(f"{w}: source {source_id} unresolved")
            used.add(source_id)
        if u["replacement_in_batch"]:
            ms = [m for m in mechs if m["id"] == r]
            if len(ms) != 1:
                err(f"{w}: replacement appears {len(ms)} times")
                continue
            diff = [k for k in MK if k != "id" and ms[0][k] != t2recs[r][k]]
            if sorted(diff) != sorted(u["changed_fields"]):
                err(f"{w}: changed_fields {u['changed_fields']} != actual {diff}")
            if u["proposed_review_status"] != ms[0]["review_status"]:
                err(f"{w}: proposed status != replacement review_status")
            if not set(ms[0]["source_ids"]) <= set(u["source_ids"]) | set(ms[0]["source_ids"]):
                pass
        elif u["changed_fields"]:
            err(f"{w}: changed_fields must be empty without replacement")
    for r in repl:
        if r not in upmap or not upmap[r]["replacement_in_batch"]:
            err(f"replacement {r} lacks update entry")
    for s in inv:
        if s["source_id"] not in used:
            err(f"{s['source_id']}: in inventory but cited nowhere in Task 3")
    for source_id in used:
        if source_id not in srcmap:
            err(f"cited source {source_id} missing from inventory")
    # report
    pc = Counter(p for m in mechs for p in m["pollutants"])
    print("FILES", sorted(p.name for p in D3.glob("*") if p.is_file()))
    print(
        "COUNTS mechanisms",
        len(mechs),
        "(new",
        len(mechs) - len(repl),
        "replacements",
        len(repl),
        ") sources",
        len(inv),
        "checks",
        len(checks),
        "inputs",
        len(inputs),
        "updates",
        len(ups),
    )
    print("MECH_POLLUTANTS", dict(pc))
    print("MECH_STATUS", dict(Counter(m["review_status"] for m in mechs)))
    print("MECH_GEO", dict(Counter(m["applicability"]["geographic_scope"] for m in mechs)))
    print("MECH_TOPICS", dict(Counter(m["topic"] for m in mechs)))
    print("CHECK_STATUS", dict(Counter(c["review_status"] for c in checks)))
    print("CHECK_POLLUTANTS", dict(Counter(p for c in checks for p in c["pollutants"])))
    print("INPUT_SCHEMA", dict(Counter(d["schema_availability"] for d in inputs)))
    print("INPUT_EVENT_TIME", dict(Counter(d["availability_at_event_time"] for d in inputs)))
    print("UPDATES", dict(Counter(u["assessment"] for u in ups)))
    ev = [e for m in mechs for e in m["evidence"]] + [e for c in checks for e in c["evidence"]]
    print(
        "EVIDENCE items",
        len(ev),
        dict(Counter(e["verification_status"] for e in ev)),
        dict(Counter(e["evidence_type"] for e in ev)),
    )
    if ERR:
        print("ERRORS", len(ERR))
        [print(" -", e) for e in ERR]
        return 1
    print("RESULT PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
