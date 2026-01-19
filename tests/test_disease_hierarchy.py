"""
Unit tests for MeSH Disease Hierarchy (Section 24).

Tests for granular disease categorization using MeSH tree structure.
"""

import pytest

from biograph.core.disease_hierarchy import (
    get_mesh_hierarchy,
    get_hierarchy_path,
    get_diseases_by_category,
    get_diseases_by_ta,
    search_diseases,
    get_ta_display_name,
    get_category_display_name,
    DiseaseHierarchy,
    MESH_L1_TO_TA,
    MESH_L2_CATEGORIES,
    MESH_L3_DISEASES
)


class TestMeSHHierarchy:
    """Test MeSH tree hierarchy classification."""

    def test_lung_cancer_hierarchy(self):
        """Test lung cancer classification: ONC > Solid Tumors > Lung Cancer."""
        hierarchy = get_mesh_hierarchy('C04.557.470')

        assert hierarchy.therapeutic_area == 'ONC'
        assert hierarchy.disease_category == 'SOLID_TUMORS'
        assert hierarchy.specific_disease == 'Lung Cancer'
        assert hierarchy.tree_depth == 3

    def test_alzheimers_hierarchy(self):
        """Test Alzheimer's classification: CNS > Neurodegenerative > Alzheimer's."""
        hierarchy = get_mesh_hierarchy('C10.574.062')

        assert hierarchy.therapeutic_area == 'CNS'
        assert hierarchy.disease_category == 'NEURODEGENERATIVE'
        assert hierarchy.specific_disease == "Alzheimer's Disease"

    def test_alzheimers_alternate_tree(self):
        """Test Alzheimer's via alternate MeSH tree."""
        hierarchy = get_mesh_hierarchy('C10.228.140.079')

        assert hierarchy.therapeutic_area == 'CNS'
        assert hierarchy.disease_category == 'NEURODEGENERATIVE'
        assert hierarchy.specific_disease == "Alzheimer's Disease"

    def test_breast_cancer_hierarchy(self):
        """Test breast cancer classification."""
        hierarchy = get_mesh_hierarchy('C04.557.337')

        assert hierarchy.therapeutic_area == 'ONC'
        assert hierarchy.disease_category == 'SOLID_TUMORS'
        assert hierarchy.specific_disease == 'Breast Cancer'

    def test_triple_negative_breast_cancer(self):
        """Test specific breast cancer subtype."""
        hierarchy = get_mesh_hierarchy('C04.557.337.249')

        assert hierarchy.therapeutic_area == 'ONC'
        assert hierarchy.disease_category == 'SOLID_TUMORS'
        assert hierarchy.specific_disease == 'Triple-Negative Breast Cancer'

    def test_parkinson_hierarchy(self):
        """Test Parkinson's disease classification."""
        hierarchy = get_mesh_hierarchy('C10.574.812')

        assert hierarchy.therapeutic_area == 'CNS'
        assert hierarchy.disease_category == 'NEURODEGENERATIVE'
        assert hierarchy.specific_disease == 'Parkinson Disease'

    def test_rheumatoid_arthritis_hierarchy(self):
        """Test autoimmune disease classification."""
        hierarchy = get_mesh_hierarchy('C20.111.198')

        assert hierarchy.therapeutic_area == 'IMM'
        assert hierarchy.disease_category == 'AUTOIMMUNE'
        assert hierarchy.specific_disease == 'Rheumatoid Arthritis'

    def test_type2_diabetes_hierarchy(self):
        """Test metabolic disease classification."""
        hierarchy = get_mesh_hierarchy('C18.452.394.750')

        assert hierarchy.therapeutic_area == 'CVM'
        assert hierarchy.disease_category == 'METABOLIC'
        assert hierarchy.specific_disease == 'Type 2 Diabetes'

    def test_covid19_hierarchy(self):
        """Test infectious disease classification."""
        hierarchy = get_mesh_hierarchy('C02.782.600.550')

        assert hierarchy.therapeutic_area == 'ID'
        assert hierarchy.disease_category == 'VIRAL'
        assert hierarchy.specific_disease == 'COVID-19'


class TestHierarchyPath:
    """Test hierarchy path generation."""

    def test_lung_cancer_path(self):
        """Test lung cancer hierarchy path."""
        path = get_hierarchy_path('C04.557.470')

        assert 'Oncology' in path
        assert 'Solid Tumors' in path
        assert 'Lung Cancer' in path
        assert ' > ' in path

    def test_alzheimers_path(self):
        """Test Alzheimer's hierarchy path."""
        path = get_hierarchy_path('C10.574.062')

        assert 'Central Nervous System' in path
        assert 'Neurodegenerative' in path
        assert "Alzheimer's Disease" in path


class TestDiseaseCategoryQueries:
    """Test querying diseases by category."""

    def test_get_solid_tumors(self):
        """Test getting all solid tumor diseases."""
        diseases = get_diseases_by_category('SOLID_TUMORS')

        # Should have multiple solid tumor types
        assert len(diseases) > 5

        # Check for expected cancers
        disease_names = [d[1] for d in diseases]
        assert 'Lung Cancer' in disease_names
        assert 'Breast Cancer' in disease_names
        assert 'Colorectal Cancer' in disease_names

    def test_get_neurodegenerative(self):
        """Test getting all neurodegenerative diseases."""
        diseases = get_diseases_by_category('NEURODEGENERATIVE')

        disease_names = [d[1] for d in diseases]
        assert "Alzheimer's Disease" in disease_names
        assert 'Parkinson Disease' in disease_names

    def test_get_autoimmune(self):
        """Test getting all autoimmune diseases."""
        diseases = get_diseases_by_category('AUTOIMMUNE')

        disease_names = [d[1] for d in diseases]
        assert 'Rheumatoid Arthritis' in disease_names
        assert 'Multiple Sclerosis' in disease_names


class TestTherapeuticAreaQueries:
    """Test querying by therapeutic area."""

    def test_get_oncology_diseases(self):
        """Test getting all oncology diseases."""
        diseases = get_diseases_by_ta('ONC')

        # Should have many oncology diseases
        assert len(diseases) > 10

        # Check categories
        categories = set(d[1] for d in diseases)
        assert 'SOLID_TUMORS' in categories
        assert 'HEMATOLOGIC_MALIGNANCIES' in categories

    def test_get_cns_diseases(self):
        """Test getting all CNS diseases."""
        diseases = get_diseases_by_ta('CNS')

        categories = set(d[1] for d in diseases)
        assert 'NEURODEGENERATIVE' in categories
        assert 'PSYCHIATRIC' in categories


class TestDiseaseSearch:
    """Test disease search functionality."""

    def test_search_cancer(self):
        """Test searching for cancer diseases."""
        results = search_diseases('cancer')

        # Should find multiple cancer types
        assert len(results) > 5

        # All results should be oncology
        for r in results:
            assert r.therapeutic_area == 'ONC'

    def test_search_lung(self):
        """Test searching for lung diseases."""
        results = search_diseases('lung')

        # Should find lung cancer
        names = [r.specific_disease for r in results]
        assert 'Lung Cancer' in names or 'Lung Adenocarcinoma' in names

    def test_search_alzheimer(self):
        """Test searching for Alzheimer's."""
        results = search_diseases('alzheimer')

        # Should find Alzheimer's
        assert len(results) >= 1
        assert results[0].specific_disease == "Alzheimer's Disease"


class TestTreeDepth:
    """Test tree depth calculation."""

    def test_l1_depth(self):
        """Test level 1 tree number."""
        hierarchy = get_mesh_hierarchy('C04')
        assert hierarchy.tree_depth == 1

    def test_l2_depth(self):
        """Test level 2 tree number."""
        hierarchy = get_mesh_hierarchy('C04.557')
        assert hierarchy.tree_depth == 2

    def test_l3_depth(self):
        """Test level 3 tree number."""
        hierarchy = get_mesh_hierarchy('C04.557.470')
        assert hierarchy.tree_depth == 3

    def test_l4_depth(self):
        """Test level 4 tree number."""
        hierarchy = get_mesh_hierarchy('C04.557.470.200')
        assert hierarchy.tree_depth == 4


class TestDisplayNames:
    """Test display name functions."""

    def test_ta_display_names(self):
        """Test therapeutic area display names."""
        assert get_ta_display_name('ONC') == 'Oncology'
        assert get_ta_display_name('CNS') == 'Central Nervous System'
        assert get_ta_display_name('IMM') == 'Immunology'
        assert get_ta_display_name('CVM') == 'Cardiovascular & Metabolic'

    def test_category_display_names(self):
        """Test category display names."""
        assert get_category_display_name('SOLID_TUMORS') == 'Solid Tumors'
        assert get_category_display_name('NEURODEGENERATIVE') == 'Neurodegenerative Diseases'
        assert get_category_display_name('AUTOIMMUNE') == 'Autoimmune Diseases'


class TestMappingCoverage:
    """Test that mappings have good coverage."""

    def test_l1_mappings_complete(self):
        """Test that all major disease categories have L1 mappings."""
        # All C categories should be mapped
        for cat in ['C01', 'C02', 'C04', 'C08', 'C10', 'C14', 'C18', 'C20']:
            assert cat in MESH_L1_TO_TA, f"Missing L1 mapping for {cat}"

    def test_l3_diseases_have_valid_ta(self):
        """Test that all L3 diseases have valid TA codes."""
        valid_tas = {'ONC', 'CNS', 'IMM', 'CVM', 'ID', 'RARE', 'RES', 'REN', 'OTHER'}

        for tree_number, (ta, cat, name) in MESH_L3_DISEASES.items():
            assert ta in valid_tas, f"Invalid TA '{ta}' for {tree_number} ({name})"

    def test_hierarchy_to_dict(self):
        """Test DiseaseHierarchy serialization."""
        hierarchy = get_mesh_hierarchy('C04.557.470')
        data = hierarchy.to_dict()

        assert 'mesh_tree_number' in data
        assert 'therapeutic_area' in data
        assert 'disease_category' in data
        assert 'specific_disease' in data
        assert 'hierarchy_path' in data


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_format(self):
        """Test handling of invalid MeSH format."""
        hierarchy = get_mesh_hierarchy('INVALID')

        assert hierarchy.therapeutic_area == 'UNKNOWN'
        assert hierarchy.disease_category == 'UNKNOWN'

    def test_unknown_tree_number(self):
        """Test handling of unknown but valid format tree number."""
        hierarchy = get_mesh_hierarchy('C99.999.999')

        # Should still get L1 default (UNKNOWN since C99 not mapped)
        assert hierarchy.tree_depth == 3

    def test_partial_match(self):
        """Test that partial matches work for sub-categories."""
        # C04.557.470.999 should still match to Lung Cancer category
        hierarchy = get_mesh_hierarchy('C04.557.470.999')

        assert hierarchy.therapeutic_area == 'ONC'
        assert hierarchy.disease_category == 'SOLID_TUMORS'
        # Should inherit from parent
