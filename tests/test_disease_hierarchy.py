"""
Unit tests for Therapeutic Area Disease Taxonomy (Section 24).

Tests for business-aligned disease categorization using MeSH Descriptor UIDs.
"""

import pytest

from biograph.core.disease_hierarchy import (
    get_disease_by_mesh_uid,
    get_hierarchy_path,
    get_diseases_by_segment,
    get_diseases_by_therapeutic_area,
    search_diseases,
    get_all_therapeutic_areas,
    get_segments_for_ta,
    get_taxonomy_stats,
    DiseaseHierarchy,
    DiseaseEntry,
    TherapeuticArea,
    Segment,
    DISEASE_TAXONOMY,
    SEGMENT_TO_TA,
)


class TestDiseaseByMeSHUID:
    """Test disease lookup by MeSH Descriptor UID."""

    def test_nsclc_lookup(self):
        """Test NSCLC classification: Oncology > Solid Tumors > NSCLC."""
        hierarchy = get_disease_by_mesh_uid('D002289')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Oncology'
        assert hierarchy.segment == 'Solid Tumors'
        assert hierarchy.disease_name == 'NSCLC'
        assert hierarchy.mesh_descriptor_uid == 'D002289'

    def test_lung_cancer_lookup(self):
        """Test Lung Cancer classification."""
        hierarchy = get_disease_by_mesh_uid('D008175')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Oncology'
        assert hierarchy.segment == 'Solid Tumors'
        assert hierarchy.disease_name == 'Lung Cancer'

    def test_alzheimer_lookup(self):
        """Test Alzheimer's classification: Neuroscience > Neurology > Alzheimer Disease."""
        hierarchy = get_disease_by_mesh_uid('D000544')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Neuroscience'
        assert hierarchy.segment == 'Neurology'
        assert hierarchy.disease_name == 'Alzheimer Disease'

    def test_breast_cancer_lookup(self):
        """Test Breast Cancer classification."""
        hierarchy = get_disease_by_mesh_uid('D001943')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Oncology'
        assert hierarchy.segment == 'Solid Tumors'
        assert hierarchy.disease_name == 'Breast Cancer'

    def test_triple_negative_breast_cancer(self):
        """Test specific breast cancer subtype."""
        hierarchy = get_disease_by_mesh_uid('D064726')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Oncology'
        assert hierarchy.segment == 'Solid Tumors'
        assert hierarchy.disease_name == 'Triple-Negative Breast Cancer'

    def test_parkinson_lookup(self):
        """Test Parkinson's disease classification."""
        hierarchy = get_disease_by_mesh_uid('D010300')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Neuroscience'
        assert hierarchy.segment == 'Neurology'
        assert hierarchy.disease_name == 'Parkinson Disease'

    def test_rheumatoid_arthritis_lookup(self):
        """Test autoimmune disease classification."""
        hierarchy = get_disease_by_mesh_uid('D001172')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Immunology & Inflammation'
        assert hierarchy.segment == 'Rheumatology'
        assert hierarchy.disease_name == 'Rheumatoid Arthritis'

    def test_type2_diabetes_lookup(self):
        """Test metabolic disease classification."""
        hierarchy = get_disease_by_mesh_uid('D003924')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Cardiometabolic & Renal'
        assert hierarchy.segment == 'Metabolic & Obesity'
        assert hierarchy.disease_name == 'Type 2 Diabetes'

    def test_covid19_lookup(self):
        """Test infectious disease classification."""
        hierarchy = get_disease_by_mesh_uid('D000086382')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Infectious Diseases'
        assert hierarchy.segment == 'Viral & Vaccines'
        assert hierarchy.disease_name == 'COVID-19'

    def test_multiple_myeloma_lookup(self):
        """Test hematologic malignancy classification."""
        hierarchy = get_disease_by_mesh_uid('D009101')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Oncology'
        assert hierarchy.segment == 'Hematologic Malignancies'
        assert hierarchy.disease_name == 'Multiple Myeloma'

    def test_psoriasis_lookup(self):
        """Test barrier inflammation classification."""
        hierarchy = get_disease_by_mesh_uid('D011565')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Immunology & Inflammation'
        assert hierarchy.segment == 'Barrier Inflammation'
        assert hierarchy.disease_name == 'Psoriasis'

    def test_cystic_fibrosis_lookup(self):
        """Test rare disease classification."""
        hierarchy = get_disease_by_mesh_uid('D003550')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Rare & Genetic Medicine'
        assert hierarchy.segment == 'Monogenic Rare'
        assert hierarchy.disease_name == 'Cystic Fibrosis'

    def test_amd_lookup(self):
        """Test ophthalmology disease classification."""
        hierarchy = get_disease_by_mesh_uid('D008268')

        assert hierarchy is not None
        assert hierarchy.therapeutic_area == 'Ophthalmology'
        assert hierarchy.segment == 'Retinal Disease'
        assert hierarchy.disease_name == 'Age-Related Macular Degeneration'

    def test_uid_without_d_prefix(self):
        """Test lookup with UID missing D prefix."""
        hierarchy = get_disease_by_mesh_uid('002289')

        assert hierarchy is not None
        assert hierarchy.disease_name == 'NSCLC'


class TestHierarchyPath:
    """Test hierarchy path generation."""

    def test_nsclc_path(self):
        """Test NSCLC hierarchy path."""
        path = get_hierarchy_path('D002289')

        assert 'Oncology' in path
        assert 'Solid Tumors' in path
        assert 'NSCLC' in path
        assert ' > ' in path

    def test_alzheimer_path(self):
        """Test Alzheimer's hierarchy path."""
        path = get_hierarchy_path('D000544')

        assert 'Neuroscience' in path
        assert 'Neurology' in path
        assert 'Alzheimer Disease' in path

    def test_ra_path(self):
        """Test Rheumatoid Arthritis hierarchy path."""
        path = get_hierarchy_path('D001172')

        assert 'Immunology & Inflammation' in path
        assert 'Rheumatology' in path
        assert 'Rheumatoid Arthritis' in path

    def test_unknown_uid_path(self):
        """Test hierarchy path for unknown UID."""
        path = get_hierarchy_path('D999999')

        assert 'Unknown' in path
        assert 'D999999' in path


class TestSegmentQueries:
    """Test querying diseases by segment."""

    def test_get_solid_tumors(self):
        """Test getting all solid tumor diseases."""
        diseases = get_diseases_by_segment(Segment.SOLID_TUMORS)

        # Should have multiple solid tumor types
        assert len(diseases) >= 10

        # Check for expected cancers
        disease_names = [d.disease_name for d in diseases]
        assert 'Lung Cancer' in disease_names
        assert 'Breast Cancer' in disease_names
        assert 'Colorectal Cancer' in disease_names
        assert 'NSCLC' in disease_names

    def test_get_hematologic_malignancies(self):
        """Test getting all hematologic malignancies."""
        diseases = get_diseases_by_segment(Segment.HEMATOLOGIC_MALIGNANCIES)

        disease_names = [d.disease_name for d in diseases]
        assert 'Multiple Myeloma' in disease_names
        assert 'Acute Myeloid Leukemia' in disease_names

    def test_get_neurology_diseases(self):
        """Test getting all neurology diseases."""
        diseases = get_diseases_by_segment(Segment.NEUROLOGY)

        disease_names = [d.disease_name for d in diseases]
        assert 'Alzheimer Disease' in disease_names
        assert 'Parkinson Disease' in disease_names
        assert 'Multiple Sclerosis' in disease_names

    def test_get_psychiatry_diseases(self):
        """Test getting all psychiatry diseases."""
        diseases = get_diseases_by_segment(Segment.PSYCHIATRY)

        disease_names = [d.disease_name for d in diseases]
        assert 'Schizophrenia' in disease_names
        assert 'Major Depressive Disorder' in disease_names

    def test_get_rheumatology_diseases(self):
        """Test getting all rheumatology diseases."""
        diseases = get_diseases_by_segment(Segment.RHEUMATOLOGY)

        disease_names = [d.disease_name for d in diseases]
        assert 'Rheumatoid Arthritis' in disease_names
        assert 'Systemic Lupus Erythematosus' in disease_names


class TestTherapeuticAreaQueries:
    """Test querying by therapeutic area."""

    def test_get_oncology_diseases(self):
        """Test getting all oncology diseases."""
        diseases = get_diseases_by_therapeutic_area(TherapeuticArea.ONCOLOGY)

        # Should have many oncology diseases
        assert len(diseases) >= 20

        # Check segments
        segments = set(d.segment for d in diseases)
        assert 'Solid Tumors' in segments
        assert 'Hematologic Malignancies' in segments

    def test_get_neuroscience_diseases(self):
        """Test getting all neuroscience diseases."""
        diseases = get_diseases_by_therapeutic_area(TherapeuticArea.NEUROSCIENCE)

        segments = set(d.segment for d in diseases)
        assert 'Neurology' in segments
        assert 'Psychiatry' in segments

    def test_get_immunology_diseases(self):
        """Test getting all immunology diseases."""
        diseases = get_diseases_by_therapeutic_area(TherapeuticArea.IMMUNOLOGY_INFLAMMATION)

        segments = set(d.segment for d in diseases)
        assert 'Rheumatology' in segments
        assert 'Barrier Inflammation' in segments

    def test_get_cardiometabolic_diseases(self):
        """Test getting all cardiometabolic diseases."""
        diseases = get_diseases_by_therapeutic_area(TherapeuticArea.CARDIOMETABOLIC_RENAL)

        disease_names = [d.disease_name for d in diseases]
        assert 'Type 2 Diabetes' in disease_names
        assert 'Heart Failure' in disease_names

    def test_get_infectious_diseases(self):
        """Test getting all infectious diseases."""
        diseases = get_diseases_by_therapeutic_area(TherapeuticArea.INFECTIOUS_DISEASES)

        disease_names = [d.disease_name for d in diseases]
        assert 'COVID-19' in disease_names
        assert 'HIV/AIDS' in disease_names


class TestDiseaseSearch:
    """Test disease search functionality."""

    def test_search_cancer(self):
        """Test searching for cancer diseases."""
        results = search_diseases('cancer')

        # Should find multiple cancer types
        assert len(results) >= 5

        # All results should be oncology
        for r in results:
            assert r.therapeutic_area == 'Oncology'

    def test_search_lung(self):
        """Test searching for lung diseases."""
        results = search_diseases('lung')

        # Should find lung cancer
        names = [r.disease_name for r in results]
        assert 'Lung Cancer' in names or 'NSCLC' in names or 'Small Cell Lung Cancer' in names

    def test_search_alzheimer(self):
        """Test searching for Alzheimer's."""
        results = search_diseases('alzheimer')

        # Should find Alzheimer's
        assert len(results) >= 1
        assert results[0].disease_name == 'Alzheimer Disease'

    def test_search_by_synonym(self):
        """Test searching by synonym."""
        results = search_diseases('AML')  # Synonym for Acute Myeloid Leukemia

        assert len(results) >= 1
        assert results[0].disease_name == 'Acute Myeloid Leukemia'

    def test_search_by_abbreviation(self):
        """Test searching by abbreviation."""
        results = search_diseases('CLL')  # Chronic Lymphocytic Leukemia

        assert len(results) >= 1
        assert results[0].disease_name == 'Chronic Lymphocytic Leukemia'

    def test_search_case_insensitive(self):
        """Test case-insensitive search."""
        results1 = search_diseases('BREAST')
        results2 = search_diseases('breast')

        assert len(results1) == len(results2)

    def test_search_limit(self):
        """Test search result limit."""
        results = search_diseases('cancer', limit=3)

        assert len(results) <= 3


class TestTherapeuticAreaListing:
    """Test therapeutic area and segment listing."""

    def test_get_all_therapeutic_areas(self):
        """Test listing all therapeutic areas."""
        tas = get_all_therapeutic_areas()

        assert 'Oncology' in tas
        assert 'Neuroscience' in tas
        assert 'Immunology & Inflammation' in tas
        assert 'Cardiometabolic & Renal' in tas
        assert 'Infectious Diseases' in tas
        assert 'Rare & Genetic Medicine' in tas
        assert 'Ophthalmology' in tas
        assert 'Specialty & Other' in tas
        assert len(tas) == 8

    def test_get_segments_for_oncology(self):
        """Test listing segments for oncology."""
        segments = get_segments_for_ta(TherapeuticArea.ONCOLOGY)

        assert 'Solid Tumors' in segments
        assert 'Hematologic Malignancies' in segments

    def test_get_segments_for_neuroscience(self):
        """Test listing segments for neuroscience."""
        segments = get_segments_for_ta(TherapeuticArea.NEUROSCIENCE)

        assert 'Neurology' in segments
        assert 'Psychiatry' in segments


class TestDiseaseEntrySerialization:
    """Test DiseaseEntry and DiseaseHierarchy serialization."""

    def test_hierarchy_to_dict(self):
        """Test DiseaseHierarchy serialization."""
        hierarchy = get_disease_by_mesh_uid('D002289')
        data = hierarchy.to_dict()

        assert 'mesh_descriptor_uid' in data
        assert 'therapeutic_area' in data
        assert 'segment' in data
        assert 'disease_name' in data
        assert 'market_driver_anchor' in data
        assert 'hierarchy_path' in data
        assert 'synonyms' in data

    def test_disease_entry_to_dict(self):
        """Test DiseaseEntry serialization."""
        entry = DISEASE_TAXONOMY['D002289']
        data = entry.to_dict()

        assert data['mesh_descriptor_uid'] == 'D002289'
        assert data['name'] == 'NSCLC'
        assert data['segment'] == 'Solid Tumors'
        assert data['therapeutic_area'] == 'Oncology'


class TestTaxonomyStats:
    """Test taxonomy statistics."""

    def test_get_taxonomy_stats(self):
        """Test taxonomy statistics function."""
        stats = get_taxonomy_stats()

        assert 'total_diseases' in stats
        assert 'therapeutic_areas' in stats
        assert 'segments' in stats
        assert 'diseases_by_ta' in stats
        assert 'diseases_by_segment' in stats

        # Should have substantial number of diseases
        assert stats['total_diseases'] >= 80

        # Should have 8 therapeutic areas
        assert stats['therapeutic_areas'] == 8

        # Oncology should have many diseases
        assert stats['diseases_by_ta']['Oncology'] >= 20


class TestMappingCoverage:
    """Test that mappings have good coverage."""

    def test_all_segments_have_ta(self):
        """Test that all segments have a therapeutic area."""
        for segment in Segment:
            assert segment in SEGMENT_TO_TA, f"Segment {segment} missing from SEGMENT_TO_TA"

    def test_all_diseases_have_valid_segment(self):
        """Test that all diseases have valid segments."""
        for mesh_uid, entry in DISEASE_TAXONOMY.items():
            assert entry.segment in Segment, f"Invalid segment for {mesh_uid}"

    def test_therapeutic_areas_match_segments(self):
        """Test that disease TAs match their segment's TA."""
        for mesh_uid, entry in DISEASE_TAXONOMY.items():
            expected_ta = SEGMENT_TO_TA[entry.segment]
            actual_ta = entry.therapeutic_area
            assert actual_ta == expected_ta, f"TA mismatch for {mesh_uid}"


class TestSingleCanonicalLocation:
    """Test that diseases have single canonical locations (no polyhierarchy)."""

    def test_no_duplicate_uids(self):
        """Test that each MeSH UID appears only once."""
        seen_uids = set()
        for mesh_uid in DISEASE_TAXONOMY.keys():
            assert mesh_uid not in seen_uids, f"Duplicate MeSH UID: {mesh_uid}"
            seen_uids.add(mesh_uid)

    def test_alzheimer_single_location(self):
        """Test that Alzheimer's has a single classification (not polyhierarchy)."""
        # Search for all Alzheimer entries
        results = search_diseases('alzheimer')

        # Should only find one Alzheimer Disease entry
        alzheimer_entries = [r for r in results if r.disease_name == 'Alzheimer Disease']
        assert len(alzheimer_entries) == 1

    def test_parkinson_single_location(self):
        """Test that Parkinson's has a single classification."""
        results = search_diseases('parkinson')

        parkinson_entries = [r for r in results if r.disease_name == 'Parkinson Disease']
        assert len(parkinson_entries) == 1

    def test_als_is_neurology_not_movement(self):
        """Test that ALS is classified under Neurology, not Movement Disorders."""
        hierarchy = get_disease_by_mesh_uid('D000690')

        assert hierarchy is not None
        assert hierarchy.segment == 'Neurology'
        assert hierarchy.therapeutic_area == 'Neuroscience'


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_unknown_uid_returns_none(self):
        """Test handling of unknown MeSH UID."""
        hierarchy = get_disease_by_mesh_uid('D999999')

        assert hierarchy is None

    def test_invalid_uid_format(self):
        """Test handling of invalid UID format."""
        hierarchy = get_disease_by_mesh_uid('INVALID')

        assert hierarchy is None

    def test_empty_search(self):
        """Test empty search query."""
        results = search_diseases('xyznonexistent')

        assert len(results) == 0


class TestSynonyms:
    """Test synonym functionality."""

    def test_nsclc_synonyms(self):
        """Test NSCLC has expected synonyms."""
        entry = DISEASE_TAXONOMY['D002289']

        assert 'Non-Small Cell Lung Cancer' in entry.synonyms
        assert 'Carcinoma, Non-Small-Cell Lung' in entry.synonyms

    def test_ra_synonyms(self):
        """Test RA has expected synonyms."""
        entry = DISEASE_TAXONOMY['D001172']

        assert 'RA' in entry.synonyms
        assert 'Arthritis, Rheumatoid' in entry.synonyms

    def test_diabetes_synonyms(self):
        """Test Type 2 Diabetes has expected synonyms."""
        entry = DISEASE_TAXONOMY['D003924']

        assert 'T2D' in entry.synonyms
        assert 'Diabetes Mellitus, Type 2' in entry.synonyms
