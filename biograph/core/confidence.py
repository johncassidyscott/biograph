"""
BioGraph MVP v8.2 - Linkage Confidence Engine

Per Section 22 of the spec, this module computes LINKAGE CONFIDENCE for assertions.

Linkage Confidence = probability that the LINK (assertion) is correctly resolved
under BioGraph rules. It is NOT:
- probability the biology is true
- probability a drug works
- investment recommendation confidence

This measures the quality of ENTITY RESOLUTION and EVIDENCE-BACKED LINKAGE.
"""

from typing import Any, Dict, List, Optional
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta
import json


class LinkMethod(str, Enum):
    """How the assertion was created."""
    DETERMINISTIC = "DETERMINISTIC"          # Exact ID match from authoritative source
    CURATED = "CURATED"                      # Human curator approved
    ML_SUGGESTED_APPROVED = "ML_SUGGESTED_APPROVED"  # ML suggested, then curator approved


class ConfidenceBand(str, Enum):
    """User-facing confidence bands."""
    HIGH = "HIGH"      # score >= 0.90 (green)
    MEDIUM = "MEDIUM"  # 0.75 <= score < 0.90 (yellow)
    LOW = "LOW"        # score < 0.75 (orange/red)


class SupportType(str, Enum):
    """Evidence support type."""
    PRIMARY = "PRIMARY"      # Direct evidence for the assertion
    SECONDARY = "SECONDARY"  # Supporting/corroborating evidence
    CONTEXT = "CONTEXT"      # Contextual/background evidence (e.g., news)


# Method baselines (Section 22D.1)
METHOD_BASELINES = {
    LinkMethod.DETERMINISTIC: 0.95,
    LinkMethod.CURATED: 0.90,
    LinkMethod.ML_SUGGESTED_APPROVED: 0.75,
}

# Method caps (Section 22D - CAPS)
METHOD_CAPS = {
    LinkMethod.DETERMINISTIC: 0.99,
    LinkMethod.ML_SUGGESTED_APPROVED: 0.85,
    LinkMethod.CURATED: 1.00,  # No cap for curated
}

# Source tier weights (Section 22D.3)
SOURCE_TIER_WEIGHTS = {
    'sec_edgar': 0.02,
    'sec_edgar_exhibit': 0.02,
    'opentargets': 0.015,
    'chembl': 0.015,
    'wikidata': 0.005,
    'news_metadata': 0.001,  # Minimal weight, never sole evidence
}

SOURCE_TIER_CAPS = {
    'sec_edgar': 0.06,
    'sec_edgar_exhibit': 0.06,
    'opentargets': 0.05,
    'chembl': 0.05,
}

# Band thresholds (Section 22D - BANDS)
BAND_THRESHOLDS = {
    ConfidenceBand.HIGH: 0.90,
    ConfidenceBand.MEDIUM: 0.75,
}


@dataclass
class EvidenceInfo:
    """Evidence information for confidence computation."""
    evidence_id: int
    source_system: str
    observed_at: datetime
    support_type: SupportType = SupportType.PRIMARY


@dataclass
class ConfidenceResult:
    """Result of confidence computation."""
    score: float
    band: ConfidenceBand
    method: LinkMethod
    rationale: Dict[str, Any]


def get_confidence_band(score: float) -> ConfidenceBand:
    """
    Get confidence band from numeric score.

    Per Section 22D - BANDS:
    - HIGH: score >= 0.90
    - MEDIUM: 0.75 <= score < 0.90
    - LOW: score < 0.75

    Args:
        score: Numeric confidence score (0.0 to 1.0)

    Returns:
        ConfidenceBand enum value
    """
    if score >= BAND_THRESHOLDS[ConfidenceBand.HIGH]:
        return ConfidenceBand.HIGH
    elif score >= BAND_THRESHOLDS[ConfidenceBand.MEDIUM]:
        return ConfidenceBand.MEDIUM
    else:
        return ConfidenceBand.LOW


def compute_link_confidence(
    method: LinkMethod,
    evidence_list: List[EvidenceInfo],
    curator_delta: float = 0.0,
    curator_justification: Optional[str] = None
) -> ConfidenceResult:
    """
    Compute linkage confidence for an assertion.

    Per Section 22D, score is computed deterministically from:
    1. Method baseline
    2. Evidence count bonus
    3. Source tier weights
    4. Evidence agreement
    5. Recency bonus (optional)
    6. Curator delta (explicitly recorded)

    Args:
        method: How the assertion was created
        evidence_list: List of evidence supporting the assertion
        curator_delta: Curator adjustment (-0.10 to +0.10)
        curator_justification: Required if curator_delta != 0

    Returns:
        ConfidenceResult with score, band, method, and rationale

    Raises:
        ValueError: If validation fails (e.g., news-only assertion)
    """
    # Validate inputs
    if not evidence_list:
        raise ValueError("Assertion must have at least one evidence record")

    if curator_delta != 0.0 and not curator_justification:
        raise ValueError("Curator delta requires justification")

    if not (-0.10 <= curator_delta <= 0.10):
        raise ValueError("Curator delta must be between -0.10 and +0.10")

    # Count evidence by source system
    evidence_by_source: Dict[str, int] = {}
    source_systems_seen: set = set()

    for ev in evidence_list:
        evidence_by_source[ev.source_system] = evidence_by_source.get(ev.source_system, 0) + 1
        source_systems_seen.add(ev.source_system)

    # Validate news-only assertion (Section 22E.1)
    if source_systems_seen == {'news_metadata'}:
        raise ValueError(
            "NEWS_METADATA can NEVER be the sole evidence for an assertion "
            "(Section 22E.1)"
        )

    # 1. Method baseline (Section 22D.1)
    base_score = METHOD_BASELINES[method]

    # 2. Evidence count bonus (Section 22D.2)
    # +0.01 per additional evidence, capped at +0.03
    evidence_count = len(evidence_list)
    evidence_bonus = min(0.03, max(0, (evidence_count - 1) * 0.01))

    # 3. Source tier weights (Section 22D.3)
    source_bonus = 0.0
    source_contributions: Dict[str, float] = {}

    for source_system, count in evidence_by_source.items():
        if source_system in SOURCE_TIER_WEIGHTS:
            weight = SOURCE_TIER_WEIGHTS[source_system]
            contribution = count * weight

            # Apply tier cap if applicable
            if source_system in SOURCE_TIER_CAPS:
                contribution = min(SOURCE_TIER_CAPS[source_system], contribution)

            source_contributions[source_system] = contribution
            source_bonus += contribution

    # 4. Evidence agreement (simplified for now)
    # If all evidence is from same source tier, add agreement bonus
    agreement_bonus = 0.0
    primary_sources = {'sec_edgar', 'sec_edgar_exhibit', 'opentargets', 'chembl'}
    primary_evidence_count = sum(1 for ev in evidence_list if ev.source_system in primary_sources)

    if primary_evidence_count > 1:
        agreement_bonus = 0.02

    # 5. Recency bonus (Section 22D.5)
    recency_bonus = 0.0
    cutoff_date = datetime.now() - timedelta(days=180)  # 6 months
    recent_evidence_count = sum(1 for ev in evidence_list if ev.observed_at >= cutoff_date)

    if recent_evidence_count >= 2:
        recency_bonus = 0.01

    # Compute uncapped score
    uncapped_score = (
        base_score +
        evidence_bonus +
        source_bonus +
        agreement_bonus +
        recency_bonus +
        curator_delta
    )

    # Apply method cap (Section 22D - CAPS)
    cap = METHOD_CAPS[method]
    final_score = min(cap, uncapped_score)

    # Record which caps were applied
    caps_applied = []
    if final_score < uncapped_score:
        caps_applied.append(f"{method.value.lower()}_cap_{cap}")

    # Ensure score is in valid range
    final_score = max(0.0, min(1.0, final_score))

    # Get band
    band = get_confidence_band(final_score)

    # Build rationale JSON (Section 22F)
    rationale = {
        "method": method.value,
        "evidence_count": evidence_count,
        "evidence_by_source": evidence_by_source,
        "base_score": float(base_score),
        "evidence_bonus": float(evidence_bonus),
        "source_bonus": float(source_bonus),
        "source_contributions": {k: float(v) for k, v in source_contributions.items()},
        "agreement_bonus": float(agreement_bonus),
        "recency_bonus": float(recency_bonus),
        "curator_delta": float(curator_delta),
        "curator_justification": curator_justification,
        "caps_applied": caps_applied,
        "final_score": float(final_score),
        "band": band.value,
    }

    return ConfidenceResult(
        score=final_score,
        band=band,
        method=method,
        rationale=rationale
    )


def compute_and_store_confidence(
    cursor: Any,
    assertion_id: int,
    method: LinkMethod,
    curator_delta: float = 0.0,
    curator_justification: Optional[str] = None
) -> ConfidenceResult:
    """
    Compute confidence and update assertion table.

    This is the main entry point for updating assertion confidence.
    Fetches evidence from database, computes confidence, and stores result.

    Args:
        cursor: Database cursor
        assertion_id: Assertion ID to update
        method: Link method for the assertion
        curator_delta: Optional curator adjustment
        curator_justification: Required if curator_delta != 0

    Returns:
        ConfidenceResult

    Raises:
        ValueError: If validation fails
    """
    # Fetch evidence for this assertion
    cursor.execute("""
        SELECT
            e.evidence_id,
            e.source_system,
            e.observed_at,
            COALESCE(ae.support_type, 'PRIMARY') as support_type
        FROM assertion_evidence ae
        JOIN evidence e ON ae.evidence_id = e.evidence_id
        WHERE ae.assertion_id = %s
        AND e.deleted_at IS NULL
        ORDER BY e.observed_at DESC
    """, (assertion_id,))

    rows = cursor.fetchall()

    if not rows:
        raise ValueError(f"Assertion {assertion_id} has no evidence")

    # Build evidence list
    evidence_list = [
        EvidenceInfo(
            evidence_id=row[0],
            source_system=row[1],
            observed_at=row[2],
            support_type=SupportType(row[3]) if row[3] else SupportType.PRIMARY
        )
        for row in rows
    ]

    # Compute confidence
    result = compute_link_confidence(
        method=method,
        evidence_list=evidence_list,
        curator_delta=curator_delta,
        curator_justification=curator_justification
    )

    # Update assertion table
    cursor.execute("""
        UPDATE assertion
        SET
            link_confidence_score = %s,
            link_confidence_band = %s,
            link_method = %s,
            link_rationale_json = %s,
            curator_delta = %s,
            updated_at = NOW()
        WHERE assertion_id = %s
    """, (
        result.score,
        result.band.value,
        result.method.value,
        json.dumps(result.rationale),
        curator_delta,
        assertion_id
    ))

    return result


def validate_confidence_required(cursor: Any, assertion_id: int) -> None:
    """
    Validate that assertion has required confidence fields.

    Per Section 22E.2: Every assertion used in explanations MUST have:
    - link_confidence_score
    - link_confidence_band
    - link_method
    - link_rationale_json

    Args:
        cursor: Database cursor
        assertion_id: Assertion ID to validate

    Raises:
        ValueError: If required fields are missing
    """
    cursor.execute("""
        SELECT
            link_confidence_score,
            link_confidence_band,
            link_method,
            link_rationale_json
        FROM assertion
        WHERE assertion_id = %s
    """, (assertion_id,))

    row = cursor.fetchone()

    if not row:
        raise ValueError(f"Assertion {assertion_id} not found")

    score, band, method, rationale = row

    missing = []
    if score is None:
        missing.append("link_confidence_score")
    if band is None:
        missing.append("link_confidence_band")
    if method is None:
        missing.append("link_method")
    if rationale is None:
        missing.append("link_rationale_json")

    if missing:
        raise ValueError(
            f"Assertion {assertion_id} is missing required confidence fields: "
            f"{', '.join(missing)} (Section 22E.2)"
        )


def get_rationale_bullets(rationale_json: Dict[str, Any]) -> List[str]:
    """
    Generate user-friendly rationale bullets from rationale JSON.

    Per Section 22C, always display:
    - method
    - short rationale bullets (drivers)
    - evidence list

    Args:
        rationale_json: Rationale JSON from compute_link_confidence

    Returns:
        List of human-readable bullet points
    """
    bullets = []

    # Method
    method = rationale_json.get("method", "UNKNOWN")
    bullets.append(f"Method: {method}")

    # Evidence count and sources
    evidence_count = rationale_json.get("evidence_count", 0)
    evidence_by_source = rationale_json.get("evidence_by_source", {})

    source_summary = ", ".join(
        f"{count} {source}" for source, count in evidence_by_source.items()
    )
    bullets.append(f"{evidence_count} evidence source{'s' if evidence_count != 1 else ''}: {source_summary}")

    # Key drivers
    base_score = rationale_json.get("base_score", 0.0)
    bullets.append(f"Base confidence: {base_score:.2f} ({method})")

    if rationale_json.get("evidence_bonus", 0) > 0:
        bullets.append(f"+{rationale_json['evidence_bonus']:.2f} for multiple evidence sources")

    if rationale_json.get("source_bonus", 0) > 0:
        bullets.append(f"+{rationale_json['source_bonus']:.2f} from high-quality sources (SEC/OpenTargets)")

    if rationale_json.get("agreement_bonus", 0) > 0:
        bullets.append(f"+{rationale_json['agreement_bonus']:.2f} for evidence agreement")

    if rationale_json.get("curator_delta", 0) != 0:
        delta = rationale_json["curator_delta"]
        justification = rationale_json.get("curator_justification", "No justification provided")
        bullets.append(f"Curator adjustment: {delta:+.2f} ({justification})")

    if rationale_json.get("caps_applied"):
        caps = ", ".join(rationale_json["caps_applied"])
        bullets.append(f"Cap applied: {caps}")

    return bullets
