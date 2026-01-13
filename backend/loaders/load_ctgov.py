#!/usr/bin/env python3
"""
ClinicalTrials.gov v2 loader (simple + robust)

What it does:
- Queries CT.gov v2 studies for a few condition queries
- Creates/updates:
  - entity(kind='trial', canonical_id='NCT:<id>')
  - trial table row (phase/status/dates)
  - company entity for lead sponsor (CTG_SPONSOR:<slug>)
  - drug entities for DRUG/BIOLOGICAL interventions (CTG_INT:<slug>)
  - edges: trial->company (sponsored_by), trial->disease (for_condition), trial->drug (studies)

Run:
  cd /workspaces/biograph
  python -m backend.loaders.load_ctgov
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from psycopg.rows import dict_row

from backend.app.db import get_conn

BASE = "https://clinicaltrials.gov/api/v2/studies"


# -------------------------
# small helpers
# -------------------------
def get_path(d: Dict[str, Any], path: List[str], default=None):
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def slug(s: str) -> str:
    return (
        s.strip()
        .lower()
        .replace("&", " and ")
        .replace("/", " ")
        .replace(",", " ")
        .replace("(", " ")
        .replace(")", " ")
        .replace(".", " ")
        .replace("'", "")
    ).split()
    # join after split to normalize whitespace
    # (done this way to keep it dependency-free)


def slug_join(words: List[str]) -> str:
    return "_".join(words[:12])  # cap length a bit


def parse_date(s: Optional[str]) -> Optional[dt.date]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def phase_to_min(phase_raw: Optional[str]) -> Optional[int]:
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


# -------------------------
# extraction
# -------------------------
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

    nct_id = get_path(ps, ["identificationModule", "nctId"])
    if not nct_id:
        return None

    title = (
        get_path(ps, ["identificationModule", "officialTitle"])
        or get_path(ps, ["identificationModule", "briefTitle"])
    )

    overall_status = get_path(ps, ["statusModule", "overallStatus"])
    study_type = get_path(ps, ["designModule", "studyType"])

    phases = get_path(ps, ["designModule", "phases"])
    if isinstance(phases, list):
        phase_raw = ",".join([str(x) for x in phases])
    elif isinstance(phases, str):
        phase_raw = phases
    else:
        phase_raw = None
    phase_min = phase_to_min(phase_raw)

    start_date = parse_date(get_path(ps, ["statusModule", "startDateStruct", "date"]))
    primary_completion_date = parse_date(
        get_path(ps, ["statusModule", "primaryCompletionDateStruct", "date"])
    )
    completion_date = parse_date(get_path(ps, ["statusModule", "completionDateStruct", "date"]))
    last_update_posted = parse_date(
        get_path(study, ["derivedSection", "miscInfoModule", "lastUpdatePostDateStruct", "date"])
    )

    sponsor_name = get_path(ps, ["sponsorsCollaboratorsModule", "leadSponsor", "name"])

    conditions = get_path(ps, ["conditionsModule", "conditions"], default=[])
    if not isinstance(conditions, list):
        conditions = []
    conditions = [str(c).strip() for c in conditions if c]

    interventions: List[Tuple[str, str]] = []
    raw_ints = get_path(ps, ["armsInterventionsModule", "interventions"], default=[])
    if isinstance(raw_ints, list):
        for it in raw_ints:
            itype = it.get("type")
            name = it.get("name")
            if itype and name:
                interventions.append((str(itype), str(name).strip()))

    return StudyExtract(
        nct_id=str(nct_id),
        title=str(title).strip() if title else None,
        overall_status=str(overall_status).strip() if overall_status else None,
        phase_raw=str(phase_raw).strip() if phase_raw else None,
        phase_min=phase_min,
        study_type=str(study_type).strip() if study_type else None,
        start_date=start_date,
        primary_completion_date=primary_completion_date,
        completion_date=completion_date,
        last_update_posted=last_update_posted,
        sponsor_name=str(sponsor_name).strip() if sponsor_name else None,
        conditions=conditions,
        interventions=interventions,
    )


# -------------------------
# CT.gov API pagination
# -------------------------
def fetch_studies(query_cond: str, page_size: int = 200) -> Iterable[Dict[str, Any]]:
    params = {
        "query.cond": query_cond,
        "pageSize": str(page_size),
        "format": "json",
    }
    page_token: Optional[str] = None

    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)

        url = BASE + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url) as r:
            payload = json.loads(r.read().decode("utf-8"))

        for s in (payload.get("studies") or []):
            yield s

        page_token = payload.get("nextPageToken")
        if not page_token:
            break

        time.sleep(0.2)


# -------------------------
# DB linking helpers
# -------------------------
def build_disease_lookup() -> Dict[str, int]:
    """
    Returns map: lowercase disease name/alias -> entity.id
    Uses dict_row to avoid tuple/dict confusion.
    """
    lookup: Dict[str, int] = {}
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select e.id as id, e.name as name, a.alias as alias
                from entity e
                left join alias a on a.entity_id = e.id
                where e.kind = 'disease'
                """
            )
            for r in cur.fetchall():
                eid = int(r["id"])
                name = r.get("name")
                alias = r.get("alias")
                if name:
                    lookup[str(name).lower()] = eid
                if alias:
                    lookup[str(alias).lower()] = eid
    return lookup


def upsert_entity(cur, kind: str, canonical_id: str, name: str) -> int:
    cur.execute(
        """
        insert into entity (kind, canonical_id, name)
        values (%s, %s, %s)
        on conflict (kind, canonical_id) do update
          set name = excluded.name,
              updated_at = now()
        returning id
        """,
        (kind, canonical_id, name),
    )
    return int(cur.fetchone()[0])


def insert_edge(cur, src_id: int, predicate: str, dst_id: int, source: str) -> None:
    cur.execute(
        """
        insert into edge (src_id, predicate, dst_id, source)
        values (%s, %s, %s, %s)
        on conflict (src_id, predicate, dst_id) do nothing
        """,
        (src_id, predicate, dst_id, source),
    )


# -------------------------
# main loader
# -------------------------
def load_ctgov(
    condition_queries: List[str],
    min_last_update: Optional[dt.date] = None,
    max_last_update: Optional[dt.date] = None,
) -> None:
    disease_lookup = build_disease_lookup()

    trials_upserted = 0
    edges_attempted = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            for q in condition_queries:
                print(f"Query: {q}")

                for raw in fetch_studies(q, page_size=200):
                    ex = extract(raw)
                    if not ex:
                        continue

                    # Optional date filter on last_update_posted
                    if ex.last_update_posted:
                        if min_last_update and ex.last_update_posted < min_last_update:
                            continue
                        if max_last_update and ex.last_update_posted > max_last_update:
                            continue

                    trial_cid = f"NCT:{ex.nct_id}"
                    trial_name = ex.title or ex.nct_id

                    trial_entity_id = upsert_entity(cur, "trial", trial_cid, trial_name)

                    # trial facts
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
                    trials_upserted += 1

                    # sponsor -> company + edge
                    if ex.sponsor_name:
                        company_slug = slug_join(slug(ex.sponsor_name))
                        company_cid = f"CTG_SPONSOR:{company_slug}"
                        company_id = upsert_entity(cur, "company", company_cid, ex.sponsor_name)
                        insert_edge(cur, trial_entity_id, "sponsored_by", company_id, "ctgov")
                        edges_attempted += 1

                    # conditions -> diseases (exact match to promoted name/alias, best-effort)
                    for cond in ex.conditions:
                        did = disease_lookup.get(cond.lower())
                        if did:
                            insert_edge(cur, trial_entity_id, "for_condition", did, "ctgov")
                            edges_attempted += 1

                    # interventions -> drugs + edges (DRUG/BIOLOGICAL only)
                    for itype, name in ex.interventions:
                        if itype.upper() not in ("DRUG", "BIOLOGICAL"):
                            continue
                        drug_slug = slug_join(slug(name))
                        drug_cid = f"CTG_INT:{drug_slug}"
                        drug_id = upsert_entity(cur, "drug", drug_cid, name)
                        insert_edge(cur, trial_entity_id, "studies", drug_id, "ctgov")
                        edges_attempted += 1

                conn.commit()

    print(f"Trials upserted: {trials_upserted}")
    print(f"Edges attempted: {edges_attempted}")


if __name__ == "__main__":
    queries = [
        "obesity",
        "alzheimer disease",
        "KRAS AND non-small cell lung cancer",
    ]

    # Keep it tight for POC (adjust anytime)
    min_d = dt.date(2024, 1, 1)
    max_d = dt.date(2025, 1, 31)

    load_ctgov(condition_queries=queries, min_last_update=min_d, max_last_update=max_d)