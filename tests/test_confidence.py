"""
Unit tests for BioGraph linkage confidence engine.

Tests Section 22 of the spec: Linkage Confidence (User-Facing).
"""

import pytest
from datetime import datetime, timedelta
from biograph.core.confidence import (
    LinkMethod,
    ConfidenceBand,
    SupportType,
    EvidenceInfo,
    get_confidence_band,
    compute_link_confidence,
    get_rationale_bullets,
    METHOD_BASELINES,
    METHOD_CAPS,
)


class TestConfidenceBands:
    """Test confidence band thresholds (Section 22D - BANDS)."""

    def test_high_band_threshold(self):
        """Score >= 0.90 should be HIGH."""
        assert get_confidence_band(0.90) == ConfidenceBand.HIGH
        assert get_confidence_band(0.95) == ConfidenceBand.HIGH
        assert get_confidence_band(1.00) == ConfidenceBand.HIGH

    def test_medium_band_threshold(self):
        """0.75 <= score < 0.90 should be MEDIUM."""
        assert get_confidence_band(0.75) == ConfidenceBand.MEDIUM
        assert get_confidence_band(0.80) == ConfidenceBand.MEDIUM
        assert get_confidence_band(0.89) == ConfidenceBand.MEDIUM

    def test_low_band_threshold(self):
        """Score < 0.75 should be LOW."""
        assert get_confidence_band(0.74) == ConfidenceBand.LOW
        assert get_confidence_band(0.50) == ConfidenceBand.LOW
        assert get_confidence_band(0.00) == ConfidenceBand.LOW


class TestMethodBaselines:
    """Test method baseline scores (Section 22D.1)."""

    def test_deterministic_baseline(self):
        """DETERMINISTIC baseline should be 0.95."""
        evidence = [EvidenceInfo(1, 'sec_edgar', datetime.now())]

        result = compute_link_confidence(
            method=LinkMethod.DETERMINISTIC,
            evidence_list=evidence
        )

        # With one evidence, should be close to baseline
        assert 0.95 <= result.score <= 0.99

    def test_curated_baseline(self):
        """CURATED baseline should be 0.90."""
        evidence = [EvidenceInfo(1, 'sec_edgar', datetime.now())]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        assert 0.90 <= result.score <= 1.00

    def test_ml_suggested_baseline(self):
        """ML_SUGGESTED_APPROVED baseline should be 0.75."""
        evidence = [EvidenceInfo(1, 'sec_edgar', datetime.now())]

        result = compute_link_confidence(
            method=LinkMethod.ML_SUGGESTED_APPROVED,
            evidence_list=evidence
        )

        assert 0.75 <= result.score <= 0.85  # Capped at 0.85


class TestEvidenceCountBonus:
    """Test evidence count bonus (Section 22D.2)."""

    def test_single_evidence_no_bonus(self):
        """Single evidence should not get count bonus."""
        evidence = [EvidenceInfo(1, 'sec_edgar', datetime.now())]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        assert result.rationale['evidence_bonus'] == 0.0

    def test_multiple_evidence_bonus(self):
        """Multiple evidence should get +0.01 per additional source."""
        evidence = [
            EvidenceInfo(1, 'sec_edgar', datetime.now()),
            EvidenceInfo(2, 'opentargets', datetime.now()),
            EvidenceInfo(3, 'chembl', datetime.now()),
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        # 3 evidence = +0.02 bonus (first is baseline, +0.01 for 2nd and 3rd)
        assert result.rationale['evidence_bonus'] == 0.02

    def test_evidence_bonus_capped(self):
        """Evidence bonus should be capped at +0.03."""
        evidence = [
            EvidenceInfo(i, 'sec_edgar', datetime.now())
            for i in range(1, 10)  # 9 evidence sources
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        # Should be capped at 0.03 despite having 8 additional sources
        assert result.rationale['evidence_bonus'] == 0.03


class TestSourceTierWeights:
    """Test source tier weights (Section 22D.3)."""

    def test_sec_edgar_bonus(self):
        """SEC EDGAR evidence should add source bonus."""
        evidence = [
            EvidenceInfo(1, 'sec_edgar', datetime.now()),
            EvidenceInfo(2, 'sec_edgar', datetime.now()),
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        # 2 * 0.02 = 0.04 (within cap of 0.06)
        assert result.rationale['source_bonus'] == pytest.approx(0.04, abs=0.001)

    def test_opentargets_bonus(self):
        """OpenTargets evidence should add source bonus."""
        evidence = [
            EvidenceInfo(1, 'opentargets', datetime.now()),
            EvidenceInfo(2, 'opentargets', datetime.now()),
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        # 2 * 0.015 = 0.03 (within cap of 0.05)
        assert result.rationale['source_bonus'] == pytest.approx(0.03, abs=0.001)

    def test_source_tier_cap(self):
        """Source tier bonus should respect caps."""
        evidence = [
            EvidenceInfo(i, 'sec_edgar', datetime.now())
            for i in range(1, 10)  # 9 SEC evidences
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        # Should be capped at 0.06 for SEC evidence
        sec_contribution = result.rationale['source_contributions'].get('sec_edgar', 0)
        assert sec_contribution <= 0.06

    def test_news_minimal_weight(self):
        """News metadata should have minimal weight."""
        evidence = [
            EvidenceInfo(1, 'sec_edgar', datetime.now()),
            EvidenceInfo(2, 'news_metadata', datetime.now()),
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        # News weight is 0.001, very small
        news_contribution = result.rationale['source_contributions'].get('news_metadata', 0)
        assert news_contribution == pytest.approx(0.001, abs=0.0001)


class TestMethodCaps:
    """Test method-specific caps (Section 22D - CAPS)."""

    def test_deterministic_cap(self):
        """DETERMINISTIC method capped at 0.99."""
        # Create many high-quality evidences to try to exceed cap
        evidence = [
            EvidenceInfo(i, 'sec_edgar', datetime.now())
            for i in range(1, 20)
        ]

        result = compute_link_confidence(
            method=LinkMethod.DETERMINISTIC,
            evidence_list=evidence
        )

        # Should be capped at 0.99
        assert result.score <= 0.99
        assert 'deterministic_cap_0.99' in result.rationale['caps_applied']

    def test_ml_suggested_cap(self):
        """ML_SUGGESTED_APPROVED method capped at 0.85."""
        # Create many high-quality evidences
        evidence = [
            EvidenceInfo(i, 'sec_edgar', datetime.now())
            for i in range(1, 20)
        ]

        result = compute_link_confidence(
            method=LinkMethod.ML_SUGGESTED_APPROVED,
            evidence_list=evidence
        )

        # Should be capped at 0.85
        assert result.score <= 0.85
        assert 'ml_suggested_approved_cap_0.85' in result.rationale['caps_applied']

    def test_curated_no_cap(self):
        """CURATED method has no cap (can reach 1.0)."""
        # Create many high-quality evidences
        evidence = [
            EvidenceInfo(i, 'sec_edgar', datetime.now())
            for i in range(1, 20)
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        # Should still be <= 1.0 but no method cap applied
        assert result.score <= 1.0


class TestNewsOnlyAssertion:
    """Test news-only assertion guardrail (Section 22E.1)."""

    def test_news_only_assertion_rejected(self):
        """Assertion with ONLY news evidence should fail."""
        evidence = [
            EvidenceInfo(1, 'news_metadata', datetime.now()),
            EvidenceInfo(2, 'news_metadata', datetime.now()),
        ]

        with pytest.raises(ValueError, match="NEWS_METADATA can NEVER be the sole evidence"):
            compute_link_confidence(
                method=LinkMethod.CURATED,
                evidence_list=evidence
            )

    def test_news_with_other_evidence_allowed(self):
        """News evidence is allowed when combined with other sources."""
        evidence = [
            EvidenceInfo(1, 'sec_edgar', datetime.now()),
            EvidenceInfo(2, 'news_metadata', datetime.now()),
        ]

        # Should succeed
        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        assert result.score > 0


class TestCuratorDelta:
    """Test curator delta adjustments (Section 22D.6)."""

    def test_curator_delta_positive(self):
        """Curator can add up to +0.05."""
        evidence = [EvidenceInfo(1, 'sec_edgar', datetime.now())]

        result_without = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        result_with = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence,
            curator_delta=0.05,
            curator_justification="Expert review confirms high confidence"
        )

        assert result_with.score == pytest.approx(result_without.score + 0.05, abs=0.001)

    def test_curator_delta_negative(self):
        """Curator can subtract up to -0.05."""
        evidence = [EvidenceInfo(1, 'sec_edgar', datetime.now())]

        result_without = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        result_with = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence,
            curator_delta=-0.05,
            curator_justification="Evidence quality concerns"
        )

        assert result_with.score == pytest.approx(result_without.score - 0.05, abs=0.001)

    def test_curator_delta_requires_justification(self):
        """Curator delta requires justification."""
        evidence = [EvidenceInfo(1, 'sec_edgar', datetime.now())]

        with pytest.raises(ValueError, match="Curator delta requires justification"):
            compute_link_confidence(
                method=LinkMethod.CURATED,
                evidence_list=evidence,
                curator_delta=0.05,
                # No justification provided
            )

    def test_curator_delta_bounds(self):
        """Curator delta must be within -0.10 to +0.10."""
        evidence = [EvidenceInfo(1, 'sec_edgar', datetime.now())]

        with pytest.raises(ValueError, match="Curator delta must be between -0.10 and \\+0.10"):
            compute_link_confidence(
                method=LinkMethod.CURATED,
                evidence_list=evidence,
                curator_delta=0.15,
                curator_justification="Too large"
            )


class TestRecencyBonus:
    """Test recency bonus (Section 22D.5)."""

    def test_recent_evidence_bonus(self):
        """Recent evidence (< 6 months) should add bonus."""
        now = datetime.now()
        evidence = [
            EvidenceInfo(1, 'sec_edgar', now - timedelta(days=30)),
            EvidenceInfo(2, 'opentargets', now - timedelta(days=60)),
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        # Should have recency bonus
        assert result.rationale['recency_bonus'] == 0.01

    def test_old_evidence_no_bonus(self):
        """Old evidence (> 6 months) should not add bonus."""
        now = datetime.now()
        evidence = [
            EvidenceInfo(1, 'sec_edgar', now - timedelta(days=365)),
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        # Should have no recency bonus
        assert result.rationale['recency_bonus'] == 0.0


class TestDeterministicScoring:
    """Test that scoring is deterministic (Section 22D)."""

    def test_same_inputs_same_outputs(self):
        """Same inputs should always produce same outputs."""
        evidence = [
            EvidenceInfo(1, 'sec_edgar', datetime(2024, 1, 1)),
            EvidenceInfo(2, 'opentargets', datetime(2024, 1, 15)),
        ]

        result1 = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        result2 = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        assert result1.score == result2.score
        assert result1.band == result2.band
        assert result1.rationale == result2.rationale


class TestRationaleBullets:
    """Test rationale bullet generation (Section 22C)."""

    def test_rationale_bullets_include_method(self):
        """Rationale bullets should include method."""
        evidence = [EvidenceInfo(1, 'sec_edgar', datetime.now())]

        result = compute_link_confidence(
            method=LinkMethod.DETERMINISTIC,
            evidence_list=evidence
        )

        bullets = get_rationale_bullets(result.rationale)

        assert any('DETERMINISTIC' in bullet for bullet in bullets)

    def test_rationale_bullets_include_evidence_count(self):
        """Rationale bullets should include evidence count."""
        evidence = [
            EvidenceInfo(1, 'sec_edgar', datetime.now()),
            EvidenceInfo(2, 'opentargets', datetime.now()),
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        bullets = get_rationale_bullets(result.rationale)

        assert any('2 evidence sources' in bullet for bullet in bullets)

    def test_rationale_bullets_include_sources(self):
        """Rationale bullets should list evidence sources."""
        evidence = [
            EvidenceInfo(1, 'sec_edgar', datetime.now()),
            EvidenceInfo(2, 'opentargets', datetime.now()),
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        bullets = get_rationale_bullets(result.rationale)

        # Should mention both sources
        sources_text = ' '.join(bullets)
        assert 'sec_edgar' in sources_text
        assert 'opentargets' in sources_text


class TestValidation:
    """Test input validation."""

    def test_empty_evidence_list_rejected(self):
        """Empty evidence list should fail."""
        with pytest.raises(ValueError, match="Assertion must have at least one evidence"):
            compute_link_confidence(
                method=LinkMethod.CURATED,
                evidence_list=[]
            )

    def test_score_bounds(self):
        """Final score should always be in [0, 1]."""
        evidence = [
            EvidenceInfo(i, 'sec_edgar', datetime.now())
            for i in range(1, 100)  # Many evidences
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence,
            curator_delta=0.10,
            curator_justification="Test max score"
        )

        assert 0.0 <= result.score <= 1.0


class TestRationaleStructure:
    """Test rationale JSON structure (Section 22F)."""

    def test_rationale_has_required_fields(self):
        """Rationale JSON should have all required fields."""
        evidence = [
            EvidenceInfo(1, 'sec_edgar', datetime.now()),
            EvidenceInfo(2, 'opentargets', datetime.now()),
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        required_fields = [
            'method',
            'evidence_count',
            'evidence_by_source',
            'base_score',
            'evidence_bonus',
            'source_bonus',
            'agreement_bonus',
            'recency_bonus',
            'curator_delta',
            'caps_applied',
            'final_score',
            'band',
        ]

        for field in required_fields:
            assert field in result.rationale, f"Missing required field: {field}"

    def test_rationale_evidence_by_source(self):
        """Rationale should count evidence by source system."""
        evidence = [
            EvidenceInfo(1, 'sec_edgar', datetime.now()),
            EvidenceInfo(2, 'sec_edgar', datetime.now()),
            EvidenceInfo(3, 'opentargets', datetime.now()),
        ]

        result = compute_link_confidence(
            method=LinkMethod.CURATED,
            evidence_list=evidence
        )

        assert result.rationale['evidence_by_source']['sec_edgar'] == 2
        assert result.rationale['evidence_by_source']['opentargets'] == 1
