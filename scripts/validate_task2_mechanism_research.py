#!/usr/bin/env python3
"""Programmatic quality checks for AirWatch Task 2 deliverables (pass 3 audit, 2026-11-07)."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path(__file__).resolve().parents[1]
    / "data/knowledge_base/research/air_pollution_mechanisms"
)
TOPICS = {"emissions", "atmospheric_chemistry", "meteorology", "transport", "measurement_quality"}
POLLUTANTS = {"pm25", "pm10", "no2", "so2", "co", "o3"}
REVIEW = {"verified", "partially_verified", "unverified"}
BASIS = {"reported_finding", "synthesis"}
EVTYPES = {
    "field_observation",
    "controlled_experiment",
    "modeling",
    "review_synthesis",
    "technical_guidance",
    "official_assessment",
}
ACCESS = {"full_text", "abstract_only", "metadata_only"}
STYPES = {"original_research", "review", "official_assessment", "technical_guidance"}
GEO = {"global", "regional", "country_specific", "site_specific"}
LOC_RE = re.compile(
    r"(p\.?\s*\d+|page\s*\d+|pp\.\s*\d+|Table\s*\d+|Fig(?:ure)?\.?\s*\d+|§\s*\d+|"
    r"section\s+[A-Za-z0-9\.]+|Homepage|PDF p\.|journal p\.)",
    re.I,
)

POL_LABEL = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO2", "so2": "SO2", "co": "CO", "o3": "O3"}
ABSTRACT_ONLY = re.compile(r"\babstract\b", re.I)
BODY_LOC = re.compile(r"(p\.\s*([2-9]|\d\d)|Table|Fig|Sect|Introduction|Conclusion)", re.I)


def emb(rec: dict[str, Any]) -> str:
    """Canonical embedding_text: derived only from record fields."""
    app = rec["applicability"]

    def j(xs: list[str] | None, default: str) -> str:
        return ", ".join(xs or []) or default

    transfer = "; ".join(app.get("transfer_limitations") or []) or "none stated"
    contradicting = "; ".join(s["observation"] for s in rec["contradicting_signals"])
    return (
        f"{rec['title']}. Pollutants: {', '.join(rec['pollutants'])} "
        f"({', '.join(POL_LABEL[p] for p in rec['pollutants'])}). "
        f"Topic: {rec['topic']}. Summary: {rec['summary']} "
        f"Mechanism: {rec['mechanism_explanation']} "
        f"Applicability: geographic scope {app['geographic_scope']}; "
        f"regions {j(app.get('regions'), app['geographic_scope'])}; "
        f"seasons {j(app.get('seasons'), 'not season-specific')}; "
        f"station types {j(app.get('station_types'), 'unspecified')}; "
        f"instrument scope: {app.get('instrument_scope') or 'not specified'}. "
        f"Transfer limitations: {transfer}. "
        f"Temporal pattern: {(rec.get('temporal_pattern') or 'not documented').rstrip('.')}. "
        f"Spatial pattern: {(rec.get('spatial_pattern') or 'not documented').rstrip('.')}. "
        f"Supporting observations: {'; '.join(s['observation'] for s in rec['expected_signals'])}. "
        f"Contradicting observations: {contradicting}. "
        f"Key limitations: {'; '.join(rec['limitations'])}."
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as e:
            raise SystemExit(f"Invalid JSON {path.name}:{i}: {e}") from e
    return rows


def main() -> int:
    mech_files = sorted(ROOT.glob("air_pollution_mechanisms_*.jsonl"))
    inv_files = sorted(ROOT.glob("source_inventory*.jsonl"))
    assert mech_files, "No mechanism files"
    assert inv_files, "No inventory files"
    records = []
    sources = []
    errors = []
    for fp in mech_files:
        n = sum(1 for line in fp.read_text(encoding="utf-8").splitlines() if line.strip())
        if n >= 300:
            errors.append(f"{fp.name} has {n} lines (>=300)")
        records.extend(load_jsonl(fp))
    for fp in inv_files:
        n = sum(1 for line in fp.read_text(encoding="utf-8").splitlines() if line.strip())
        if n >= 300:
            errors.append(f"{fp.name} has {n} lines (>=300)")
        sources.extend(load_jsonl(fp))

    for fp in sorted(ROOT.glob("*.md")) + sorted(ROOT.glob("*.py")):
        n = len(fp.read_text(encoding="utf-8").splitlines())
        if n >= 300:
            errors.append(f"{fp.name} has {n} lines (>=300)")

    rids = [r["id"] for r in records]
    if len(rids) != len(set(rids)):
        errors.append("Duplicate record ids: " + str([x for x in rids if rids.count(x) > 1][:10]))
    sids = [s["source_id"] for s in sources]
    if len(sids) != len(set(sids)):
        errors.append("Duplicate source ids")
    source_map = {s["source_id"]: s for s in sources}

    n_ev = n_ver = n_ver_loc = 0
    for r in records:
        for f in [
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
            "quantitative_findings",
            "source_ids",
            "review_status",
            "embedding_text",
        ]:
            if f not in r:
                errors.append(f"{r.get('id')} missing {f}")
        if r.get("topic") not in TOPICS:
            errors.append(f"{r['id']} bad topic")
        if r.get("review_status") not in REVIEW:
            errors.append(f"{r['id']} bad review_status")
        if not r.get("embedding_text"):
            errors.append(f"{r['id']} empty embedding_text")
        if not r.get("evidence"):
            errors.append(f"{r['id']} empty evidence")
        if set(r.get("pollutants", [])) - POLLUTANTS:
            errors.append(f"{r['id']} bad pollutants")
        app = r.get("applicability") or {}
        if app.get("geographic_scope") not in GEO:
            errors.append(f"{r['id']} bad geographic_scope")
        eids = set()
        for e in r.get("evidence", []):
            if e["id"] in eids:
                errors.append(f"{r['id']} duplicate evidence id {e['id']}")
            eids.add(e["id"])
            if e.get("source_id") not in source_map:
                errors.append(f"{r['id']} evidence source missing {e.get('source_id')}")
            if e.get("verification_status") not in REVIEW:
                errors.append(f"{r['id']} bad evidence verification")
            if e.get("evidence_type") not in EVTYPES:
                errors.append(f"{r['id']} bad evidence_type {e.get('evidence_type')}")
            n_ev += 1
            if e.get("verification_status") == "verified":
                n_ver += 1
                if LOC_RE.search(e.get("locator") or ""):
                    n_ver_loc += 1
                else:
                    errors.append(
                        f"{r['id']} verified evidence {e['id']} "
                        f"locator lacks page/table/figure/section number: {e.get('locator')!r}"
                    )
            locator = e.get("locator") or ""
            if e.get("verification_status") == "verified":
                if ABSTRACT_ONLY.search(locator) and not BODY_LOC.search(locator):
                    errors.append(
                        f"{r['id']} verified evidence {e['id']} has "
                        f"abstract-only locator: {locator!r}"
                    )
                if locator.lower().startswith("homepage") and not BODY_LOC.search(locator):
                    errors.append(
                        f"{r['id']} verified evidence {e['id']} relies only on a homepage"
                    )
        ev_status = {e.get("verification_status") for e in r.get("evidence", [])}
        if r.get("review_status") == "verified" and ev_status != {"verified"}:
            errors.append(f"{r['id']} review_status verified but evidence statuses {ev_status}")
        try:
            if r.get("embedding_text") != emb(r):
                errors.append(f"{r['id']} embedding_text inconsistent with record fields")
        except Exception as ex:
            errors.append(f"{r['id']} embedding check failed: {ex}")
        for s in r.get("expected_signals", []) + r.get("contradicting_signals", []):
            if s.get("basis") not in BASIS:
                errors.append(f"{r['id']} bad basis")
            for eid in s.get("evidence_ids", []):
                if eid not in eids:
                    errors.append(f"{r['id']} signal evidence_id unresolved {eid}")
        for q in r.get("quantitative_findings", []):
            if q.get("evidence_id") not in eids:
                errors.append(f"{r['id']} quantitative evidence_id unresolved")
        from_ev = sorted({e["source_id"] for e in r.get("evidence", [])})
        if sorted(r.get("source_ids", [])) != from_ev:
            errors.append(f"{r['id']} source_ids mismatch evidence")

    for s in sources:
        for f in [
            "source_id",
            "title",
            "authors_or_organization",
            "publisher",
            "publication_date",
            "source_type",
            "url",
            "language",
            "access_level",
            "accessed_on",
            "record_ids",
            "verification_notes",
        ]:
            if f not in s:
                errors.append(f"{s.get('source_id')} missing {f}")
        if s.get("source_type") not in STYPES:
            errors.append(f"{s['source_id']} bad source_type")
        if s.get("access_level") not in ACCESS:
            errors.append(f"{s['source_id']} bad access_level")

    rec_to_src = defaultdict(set)
    for r in records:
        for sid in r["source_ids"]:
            rec_to_src[r["id"]].add(sid)
            if r["id"] not in source_map[sid].get("record_ids", []):
                errors.append(f"Inventory {sid} missing record {r['id']}")
    for s in sources:
        for rid in s.get("record_ids", []):
            if rid not in rec_to_src:
                errors.append(f"Inventory {s['source_id']} lists unknown record {rid}")
            elif s["source_id"] not in rec_to_src[rid]:
                errors.append(f"Record {rid} missing source {s['source_id']} listed in inventory")

    for r in records:
        exp = {s["observation"].strip().lower() for s in r.get("expected_signals", [])}
        con = {s["observation"].strip().lower() for s in r.get("contradicting_signals", [])}
        both = exp & con
        if both:
            errors.append(
                f"{r['id']} same observation in expected and contradicting: {list(both)[:1]}"
            )

    print("MECHANISM_FILES", [p.name for p in mech_files])
    print("INVENTORY_FILES", [p.name for p in inv_files])
    print("N_RECORDS", len(records))
    print("N_SOURCES", len(sources))
    print("TOPICS", dict(Counter(r["topic"] for r in records)))
    print("REVIEW_STATUS", dict(Counter(r["review_status"] for r in records)))
    pols: Counter[str] = Counter()
    for r in records:
        for p in r["pollutants"]:
            pols[p] += 1
    print("POLLUTANTS", dict(pols))
    print("EVIDENCE_ITEMS", n_ev)
    print("VERIFIED_EVIDENCE", n_ver)
    print("VERIFIED_WITH_PAGE_LOCATOR", n_ver_loc)
    print(
        "LINE_COUNTS",
        {
            p.name: len(p.read_text().splitlines())
            for p in mech_files + inv_files + sorted(ROOT.glob("*.md")) + sorted(ROOT.glob("*.py"))
        },
    )
    print(
        "CHECKS bidirectional_mapping, unique_ids, line_limit<300, "
        "page_locators, no_abstract_only_verified, status_rollup, embedding_consistency"
    )
    if errors:
        print("ERRORS", len(errors))
        for e in errors[:80]:
            print(" -", e)
        return 1
    print("RESULT PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
