#!/usr/bin/env python3
"""
ClinicalTrials.gov v2 loader:
- pulls studies for a small set of condition queries
- upserts:
  - entity(kind='trial', canonical_id='NCT:<id>')
  - trial table (phase/status/dates)
  - companies (from sponsor)
  - drugs (from interventions where type is DRUG/BIOLOGICAL)
  - edges linking trial to disease/company/drug

API docs: https://clinicaltrials.gov/data-api/api
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.db import get_conn
from backend.entity_resolver import get_resolver


BASE = "https://clinicaltrials.gov/api/v2/studies"


# ---- helpers ----
def _get(d: Dict[str, Any], path: List[str], default=None):
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def parse_date(s: Optional[str]) -> Optional[dt.date]:
    # CT.gov uses various date formats; handle common ones.
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = dt.datetime.strptime(s, fmt).date()
            # normalize partial dates: if only year-month, day becomes 1; if year-only, Jan 1
            return parsed
        except ValueError:
            continue
    return None


def phase_to_min(phase_raw: Optional[str]) -> Optional[int]:
    """
    Map CT.gov phases like:
      ["PHASE1"] / "PHASE2" / "PHASE3" / "PHASE4"
      "EARLY_PHASE1" -> 1
      "PHASE1_PHASE2" -> 1
      "PHASE2_PHASE3" -> 2
    """
    if not phase_raw:
        return None
    s = phase_raw.upper()
    if "PHASE4" in s:
        return 4
    if "PHASE3" in s:
        return 3
    if "PHASE2" in s:
        return 2
    if "PHASE1" in s or "EARLY" in s:
        return 1
    return None


@dataclass
class StudyExtract:
    nct_id: str
    title: Optional[str]
    overall_status: Optional[str]
    phase_raw: Optional[str]
    phase_min: Optional[int]
    study_type: Optional[str]
    start_date: Optional[dt.date]
    primary_completion_date: Optional[dt.date]
    completion_date: Optional[dt.date]
    last_update_posted: Optional[dt.date]
    sponsor_name: Optional[str]
    conditions: List[str]
    interventions: List[Tuple[str, str]]  # (type, name)


def extract(study: Dict[str, Any]) -> Optional[StudyExtract]:
    ps = study.get("protocolSection", {})
    nct_id = _get(ps, ["identificationModule", "nctId"])
    if not nct_id:
        return None

    title = (
        _get(ps, ["identificationModule", "officialTitle"])
        or _get(ps, ["identificationModule", "briefTitle"])
    )

    overall_status = _get(ps, ["statusModule", "overallStatus"])
    study_type = _get(ps, ["designModule", "studyType"])

    # phases is usually a list; keep raw joined
    phases = _get(ps, ["designModule", "phases"])
    if isinstance(phases, list):
        phase_raw = ",".join(phases)
    else:
        phase_raw = phases if isinstance(phases, str) else None
    phase_min = phase_to_min(phase_raw)

    start_date = parse_date(_get(ps, ["statusModule", "startDateStruct", "date"]))
    primary_completion_date = parse_date(_get(ps, ["statusModule", "primaryCompletionDateStruct", "date"]))
    completion_date = parse_date(_get(ps, ["statusModule", "completionDateStruct", "date"]))
    last_update_posted = parse_date(_get(study, ["derivedSection", "miscInfoModule", "lastUpdatePostDateStruct", "date"]))

    sponsor_name = _get(ps, ["sponsorsCollaboratorsModule", "leadSponsor", "name"])

    conditions = _get(ps, ["conditionsModule", "conditions"], default=[])
    if not isinstance(conditions, list):
        conditions = []

    interventions = []
    raw_ints = _get(ps, ["armsInterventionsModule", "interventions"], default=[])
    if isinstance(raw_ints, list):
        for it in raw_ints:
            itype = it.get("type")
            name = it.get("name")
            if itype and name:
                interventions.append((str(itype), str(name)))

    return StudyExtract(
        nct_id=nct_id,
        title=title,
        overall_status=overall_status,
        phase_raw=phase_raw,
        phase_min=phase_min,
        study_type=study_type,
        start_date=start_date,
        primary_completion_date=primary_completion_date,
        completion_date=completion_date,
        last_update_posted=last_update_posted,
        sponsor_name=sponsor_name,
        conditions=[str(c) for c in conditions if c],
        interventions=interventions,
    )


def fetch_pages(query_cond: str, page_size: int = 200, count_total: bool = False) -> Iterable[Dict[str, Any]]:
    """
    Generator over studies for a query. CT.gov v2 uses nextPageToken for pagination.
    """
    params = {
        "query.cond": query_cond,
        "pageSize": str(page_size),
        "countTotal": "true" if count_total else "false",
        "format": "json",
    }
    page_token = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)

        url = BASE + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url) as r:
            payload = json.loads(r.read().decode("utf-8"))

        studies = payload.get("studies", []) or []
        for s in studies:
            yield s

        page_token = payload.get("nextPageToken")
        if not page_token:
            break

        time.sleep(0.2)  # be polite


def load_ctgov(
    condition_queries: List[str],
    min_last_update: Optional[dt.date] = None,
    max_last_update: Optional[dt.date] = None,
) -> None:
    """
    Load studies matching condition queries with entity resolution.

    Uses EntityResolver to prevent duplicate entities and track confidence scores.
    """
    # Initialize entity resolver
    resolver = get_resolver()
    resolver.load_lookup_tables()

    inserted_trials = 0
    inserted_edges = 0
    low_confidence_matches = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            for q in condition_queries:
                print(f"Query: {q}")
                for raw in fetch_pages(q, page_size=200, count_total=False):
                    ex = extract(raw)
                    if not ex:
                        continue

                    # Date filter (optional)
                    if min_last_update and ex.last_update_posted and ex.last_update_posted < min_last_update:
                        continue
                    if max_last_update and ex.last_update_posted and ex.last_update_posted > max_last_update:
                        continue

                    trial_cid = f"NCT:{ex.nct_id}"

                    # Upsert trial entity node (NCT IDs are always canonical)
                    cur.execute(
                        """
                        insert into entity (kind, canonical_id, name)
                        values (%s, %s, %s)
                        on conflict (kind, canonical_id) do update
                          set name = excluded.name,
                              updated_at = now()
                        returning id
                        """,
                        ("trial", trial_cid, ex.title or ex.nct_id),
                    )
                    trial_entity_id = cur.fetchone()[0]

                    # Upsert trial facts
                    cur.execute(
                        """
                        insert into trial (
                          nct_id, title, overall_status, phase_raw, phase_min, study_type,
                          start_date, primary_completion_date, completion_date, last_update_posted,
                          sponsor_name
                        )
                        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        on conflict (nct_id) do update set
                          title = excluded.title,
                          overall_status = excluded.overall_status,
                          phase_raw = excluded.phase_raw,
                          phase_min = excluded.phase_min,
                          study_type = excluded.study_type,
                          start_date = excluded.start_date,
                          primary_completion_date = excluded.primary_completion_date,
                          completion_date = excluded.completion_date,
                          last_update_posted = excluded.last_update_posted,
                          sponsor_name = excluded.sponsor_name
                        """,
                        (
                            ex.nct_id,
                            ex.title,
                            ex.overall_status,
                            ex.phase_raw,
                            ex.phase_min,
                            ex.study_type,
                            ex.start_date,
                            ex.primary_completion_date,
                            ex.completion_date,
                            ex.last_update_posted,
                            ex.sponsor_name,
                        ),
                    )
                    inserted_trials += 1

                    # Resolve sponsor company
                    if ex.sponsor_name:
                        company = resolver.resolve_company(ex.sponsor_name)

                        # Create edge with confidence score
                        cur.execute(
                            """
                            insert into edge (src_id, predicate, dst_id, source, confidence)
                            values (%s, 'sponsored_by', %s, 'ctgov', %s)
                            on conflict (src_id, predicate, dst_id) do update
                              set confidence = GREATEST(edge.confidence, EXCLUDED.confidence)
                            """,
                            (trial_entity_id, company.entity_id, company.confidence),
                        )
                        inserted_edges += cur.rowcount

                        if company.confidence < 0.85:
                            low_confidence_matches += 1

                    # Resolve condition diseases
                    for cond in ex.conditions:
                        disease = resolver.resolve_disease(cond)

                        cur.execute(
                            """
                            insert into edge (src_id, predicate, dst_id, source, confidence)
                            values (%s, 'for_condition', %s, 'ctgov', %s)
                            on conflict (src_id, predicate, dst_id) do update
                              set confidence = GREATEST(edge.confidence, EXCLUDED.confidence)
                            """,
                            (trial_entity_id, disease.entity_id, disease.confidence),
                        )
                        inserted_edges += cur.rowcount

                        if disease.confidence < 0.85:
                            low_confidence_matches += 1

                    # Resolve drug interventions
                    for itype, drug_name in ex.interventions:
                        if itype.upper() not in ("DRUG", "BIOLOGICAL"):
                            continue

                        drug = resolver.resolve_drug(drug_name)

                        cur.execute(
                            """
                            insert into edge (src_id, predicate, dst_id, source, confidence)
                            values (%s, 'studies', %s, 'ctgov', %s)
                            on conflict (src_id, predicate, dst_id) do update
                              set confidence = GREATEST(edge.confidence, EXCLUDED.confidence)
                            """,
                            (trial_entity_id, drug.entity_id, drug.confidence),
                        )
                        inserted_edges += cur.rowcount

                        if drug.confidence < 0.85:
                            low_confidence_matches += 1

                conn.commit()

    print(f"✓ Trials inserted: {inserted_trials}")
    print(f"✓ Edges inserted: {inserted_edges}")
    if low_confidence_matches > 0:
        print(f"⚠️  Low confidence matches (<0.85): {low_confidence_matches}")


if __name__ == "__main__":
    # POC condition queries (tight on purpose)
    # You can broaden later once you have company lists & better linking.
    queries = [
        "obesity",
        "alzheimer disease",
        "KRAS AND non-small cell lung cancer",
    ]

    # Optional time window (example: 2024-01-01 to 2025-01-31)
    min_d = dt.date(2024, 1, 1)
    max_d = dt.date(2025, 1, 31)

    load_ctgov(condition_queries=queries, min_last_update=min_d, max_last_update=max_d)