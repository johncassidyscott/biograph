"""
Unit tests for Literature and News Evidence (Section 24).

Tests PubMed resolver, MeSH resolver, and Therapeutic Area mapping.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
import xml.etree.ElementTree as ET

from biograph.integrations.pubmed import (
    fetch_pubmed_article,
    search_pubmed,
    create_pubmed_evidence,
    validate_pmid
)
from biograph.integrations.mesh import (
    fetch_mesh_live,
    get_mesh_label,
    validate_mesh_id,
    extract_tree_prefix,
    get_mesh_tree_prefixes
)
from biograph.core.therapeutic_area import (
    TherapeuticArea,
    TAMappingResult,
    map_disease_to_ta,
    map_mesh_to_ta,
    map_disease_comprehensive,
    get_ta_display_name,
    validate_ta_code
)


# ============================================================================
# PubMed Tests
# ============================================================================

class TestPubMedResolver:
    """Test PubMed article fetching and evidence creation."""

    @patch('biograph.integrations.pubmed.requests.get')
    def test_fetch_pubmed_article_success(self, mock_get):
        """Test successful PubMed article fetch."""
        # Mock XML response
        mock_xml = """<?xml version="1.0"?>
        <PubmedArticleSet>
            <PubmedArticle>
                <MedlineCitation>
                    <Article>
                        <ArticleTitle>TP53 mutations in cancer</ArticleTitle>
                        <Journal>
                            <Title>Nature</Title>
                        </Journal>
                    </Article>
                    <PubDate>
                        <Year>2023</Year>
                        <Month>Mar</Month>
                        <Day>15</Day>
                    </PubDate>
                </MedlineCitation>
                <PubmedData>
                    <ArticleIdList>
                        <ArticleId IdType="doi">10.1038/nature12345</ArticleId>
                    </ArticleIdList>
                </PubmedData>
                <MeshHeadingList>
                    <MeshHeading>
                        <DescriptorName UI="D009369">Neoplasms</DescriptorName>
                    </MeshHeading>
                    <MeshHeading>
                        <DescriptorName UI="D016158">Genes, p53</DescriptorName>
                    </MeshHeading>
                </MeshHeadingList>
            </PubmedArticle>
        </PubmedArticleSet>"""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_xml.encode('utf-8')
        mock_get.return_value = mock_response

        result = fetch_pubmed_article('12345678')

        assert result is not None
        assert result['pmid'] == '12345678'
        assert result['title'] == 'TP53 mutations in cancer'
        assert result['journal'] == 'Nature'
        assert result['publication_date'] == '2023-03-15'
        assert result['doi'] == '10.1038/nature12345'
        assert result['url'] == 'https://pubmed.ncbi.nlm.nih.gov/12345678/'
        assert result['snippet'] == 'TP53 mutations in cancer'
        assert 'D009369' in result['mesh_ids']
        assert 'D016158' in result['mesh_ids']

    @patch('biograph.integrations.pubmed.requests.get')
    def test_fetch_pubmed_article_not_found(self, mock_get):
        """Test PubMed article not found (404)."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = fetch_pubmed_article('99999999')

        assert result is None

    @patch('biograph.integrations.pubmed.requests.get')
    def test_fetch_pubmed_article_timeout(self, mock_get):
        """Test PubMed API timeout."""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()

        result = fetch_pubmed_article('12345678')

        assert result is None

    @patch('biograph.integrations.pubmed.requests.get')
    def test_fetch_pubmed_article_snippet_truncation(self, mock_get):
        """Test that long titles are truncated to 200 chars for snippet."""
        long_title = "A" * 250

        mock_xml = f"""<?xml version="1.0"?>
        <PubmedArticleSet>
            <PubmedArticle>
                <MedlineCitation>
                    <Article>
                        <ArticleTitle>{long_title}</ArticleTitle>
                        <Journal>
                            <Title>Test Journal</Title>
                        </Journal>
                    </Article>
                </MedlineCitation>
            </PubmedArticle>
        </PubmedArticleSet>"""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_xml.encode('utf-8')
        mock_get.return_value = mock_response

        result = fetch_pubmed_article('12345678')

        assert result is not None
        assert len(result['snippet']) == 200
        assert result['snippet'] == "A" * 200

    @patch('biograph.integrations.pubmed.requests.get')
    def test_search_pubmed(self, mock_get):
        """Test PubMed search."""
        mock_xml = """<?xml version="1.0"?>
        <eSearchResult>
            <IdList>
                <Id>12345678</Id>
                <Id>87654321</Id>
                <Id>11111111</Id>
            </IdList>
        </eSearchResult>"""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_xml.encode('utf-8')
        mock_get.return_value = mock_response

        result = search_pubmed('cancer AND TP53', max_results=10)

        assert len(result) == 3
        assert '12345678' in result
        assert '87654321' in result
        assert '11111111' in result

    def test_validate_pmid(self):
        """Test PMID validation."""
        # Valid PMIDs
        assert validate_pmid('12345678') is True
        assert validate_pmid('123456') is True  # 6 digits (minimum)
        assert validate_pmid('123456789012') is True  # 12 digits (maximum)

        # Invalid PMIDs
        assert validate_pmid('12345') is False  # Too short
        assert validate_pmid('1234567890123') is False  # Too long
        assert validate_pmid('ABCD1234') is False  # Non-numeric
        assert validate_pmid('') is False  # Empty

    @patch('biograph.integrations.pubmed.fetch_pubmed_article')
    def test_create_pubmed_evidence(self, mock_fetch, db_conn):
        """Test evidence creation from PubMed article."""
        # Mock article data
        mock_fetch.return_value = {
            'pmid': '12345678',
            'title': 'Test Article',
            'journal': 'Test Journal',
            'publication_date': '2023-03-15',
            'doi': '10.1234/test',
            'mesh_ids': ['D009369'],
            'url': 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
            'snippet': 'Test Article'
        }

        cursor = db_conn.cursor()

        evidence_id = create_pubmed_evidence(
            cursor=cursor,
            pmid='12345678',
            batch_id='test_batch',
            created_by='test_user'
        )

        assert evidence_id is not None

        # Verify evidence record
        cursor.execute("""
            SELECT source_system, source_record_id, license, uri, snippet
            FROM evidence
            WHERE evidence_id = %s
        """, (evidence_id,))

        row = cursor.fetchone()
        assert row[0] == 'pubmed'
        assert row[1] == '12345678'
        assert row[2] == 'NLM_PUBLIC'
        assert row[3] == 'https://pubmed.ncbi.nlm.nih.gov/12345678/'
        assert row[4] == 'Test Article'

        db_conn.rollback()

    @patch('biograph.integrations.pubmed.fetch_pubmed_article')
    def test_create_pubmed_evidence_duplicate(self, mock_fetch, db_conn):
        """Test that duplicate PubMed evidence returns existing ID."""
        mock_fetch.return_value = {
            'pmid': '12345678',
            'title': 'Test Article',
            'journal': 'Test Journal',
            'publication_date': '2023-03-15',
            'doi': None,
            'mesh_ids': [],
            'url': 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
            'snippet': 'Test Article'
        }

        cursor = db_conn.cursor()

        # Create first evidence
        evidence_id_1 = create_pubmed_evidence(cursor, '12345678')

        # Try to create duplicate
        evidence_id_2 = create_pubmed_evidence(cursor, '12345678')

        # Should return same ID
        assert evidence_id_1 == evidence_id_2

        db_conn.rollback()


# ============================================================================
# MeSH Tests
# ============================================================================

class TestMeSHResolver:
    """Test MeSH descriptor resolution."""

    @patch('biograph.integrations.mesh.requests.get')
    def test_fetch_mesh_live_descriptor(self, mock_get):
        """Test fetching MeSH descriptor."""
        mock_xml = """<?xml version="1.0"?>
        <eSummaryResult>
            <DocSum>
                <Item Name="DS_MeshTerms" Type="String">Neoplasms,Cancer,Tumor</Item>
                <Item Name="TreeNumber" Type="String">C04</Item>
            </DocSum>
        </eSummaryResult>"""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_xml.encode('utf-8')
        mock_get.return_value = mock_response

        result = fetch_mesh_live('D009369')

        assert result is not None
        assert result['id'] == 'D009369'
        assert result['label'] == 'Neoplasms'
        assert result['source'] == 'mesh'

    @patch('biograph.integrations.mesh.requests.get')
    def test_fetch_mesh_live_tree_number(self, mock_get):
        """Test fetching MeSH tree number (not descriptor)."""
        # Tree numbers don't need API call
        result = fetch_mesh_live('C04.557.470')

        assert result is not None
        assert result['id'] == 'C04.557.470'
        assert result['label'] == 'C04.557.470'  # Fallback to ID
        assert result['tree_numbers'] == ['C04.557.470']
        assert result['is_tree_number'] is True

        # Verify no API call was made
        mock_get.assert_not_called()

    @patch('biograph.integrations.mesh.requests.get')
    def test_fetch_mesh_live_not_found(self, mock_get):
        """Test MeSH descriptor not found."""
        mock_xml = """<?xml version="1.0"?>
        <eSummaryResult>
            <ERROR>Unknown UID</ERROR>
        </eSummaryResult>"""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_xml.encode('utf-8')
        mock_get.return_value = mock_response

        result = fetch_mesh_live('D999999')

        assert result is None

    @patch('biograph.integrations.mesh.cached_resolve_with_fallback')
    def test_get_mesh_label_cached(self, mock_cached_resolve, db_conn):
        """Test MeSH label retrieval with caching."""
        mock_cached_resolve.return_value = {
            'id': 'D009369',
            'label': 'Neoplasms',
            'tree_numbers': ['C04'],
            'source': 'mesh'
        }

        cursor = db_conn.cursor()
        result = get_mesh_label(cursor, 'D009369')

        assert result['label'] == 'Neoplasms'
        mock_cached_resolve.assert_called_once()

    def test_validate_mesh_id(self):
        """Test MeSH ID validation."""
        # Valid descriptor IDs
        assert validate_mesh_id('D009369') is True
        assert validate_mesh_id('D123456') is True

        # Valid supplementary concept IDs
        assert validate_mesh_id('C000656388') is True
        assert validate_mesh_id('C123456') is True

        # Valid tree numbers
        assert validate_mesh_id('C04') is True
        assert validate_mesh_id('C04.557') is True
        assert validate_mesh_id('C04.557.470') is True
        assert validate_mesh_id('A01.456.789') is True

        # Invalid IDs
        assert validate_mesh_id('E123456') is False  # Wrong prefix
        assert validate_mesh_id('D12345') is False  # Too short
        assert validate_mesh_id('C4.557') is False  # Wrong tree format
        assert validate_mesh_id('') is False  # Empty

    def test_extract_tree_prefix(self):
        """Test MeSH tree prefix extraction."""
        # Level 1
        assert extract_tree_prefix('C04.557.470', max_levels=1) == 'C04'

        # Level 2
        assert extract_tree_prefix('C04.557.470', max_levels=2) == 'C04.557'

        # Level 3
        assert extract_tree_prefix('C04.557.470', max_levels=3) == 'C04.557.470'

        # Short tree
        assert extract_tree_prefix('C04', max_levels=1) == 'C04'
        assert extract_tree_prefix('C04', max_levels=2) == 'C04'

    def test_get_mesh_tree_prefixes(self):
        """Test getting all tree prefixes from tree numbers."""
        tree_numbers = ['C04.557.470', 'C10.228.140']

        prefixes = get_mesh_tree_prefixes(tree_numbers, max_levels=2)

        # Should return all levels up to max_levels
        assert 'C04' in prefixes
        assert 'C04.557' in prefixes
        assert 'C10' in prefixes
        assert 'C10.228' in prefixes

        # Should not include full 3-level paths
        assert 'C04.557.470' not in prefixes
        assert 'C10.228.140' not in prefixes


# ============================================================================
# Therapeutic Area Tests
# ============================================================================

class TestTherapeuticAreaMapping:
    """Test Therapeutic Area mapping functionality."""

    def test_map_disease_to_ta_efo(self, db_conn):
        """Test mapping EFO disease ID to TA."""
        cursor = db_conn.cursor()

        # Test with a prepopulated EFO mapping (if exists in migration)
        # This will vary based on migration data
        result = map_disease_to_ta(cursor, 'EFO_0000400')  # Diabetes

        assert isinstance(result, TAMappingResult)
        assert result.disease_id == 'EFO_0000400'
        assert result.mapping_source == 'ontology_id'

        # Should be either CVM or UNKNOWN depending on migration data
        assert result.primary_ta in [TherapeuticArea.CVM, TherapeuticArea.UNKNOWN]

    def test_map_disease_to_ta_mondo(self, db_conn):
        """Test mapping MONDO disease ID to TA."""
        cursor = db_conn.cursor()

        result = map_disease_to_ta(cursor, 'MONDO_0007254')  # Breast cancer

        assert isinstance(result, TAMappingResult)
        assert result.disease_id == 'MONDO_0007254'
        assert result.mapping_source == 'ontology_id'

    def test_map_disease_to_ta_unknown(self, db_conn):
        """Test mapping unmapped disease returns UNKNOWN."""
        cursor = db_conn.cursor()

        result = map_disease_to_ta(cursor, 'EFO_9999999')

        assert result.primary_ta == TherapeuticArea.UNKNOWN
        assert result.disease_id == 'EFO_9999999'

    def test_map_mesh_to_ta(self, db_conn):
        """Test mapping MeSH IDs to TA."""
        cursor = db_conn.cursor()

        # Test with cancer MeSH tree (C04%)
        result = map_mesh_to_ta(cursor, ['C04.557.470', 'D009369'])

        assert isinstance(result, TAMappingResult)
        assert result.primary_ta == TherapeuticArea.ONC
        assert result.mapping_source == 'mesh'

    def test_map_mesh_to_ta_empty_list(self, db_conn):
        """Test mapping empty MeSH list returns UNKNOWN."""
        cursor = db_conn.cursor()

        result = map_mesh_to_ta(cursor, [])

        assert result.primary_ta == TherapeuticArea.UNKNOWN

    def test_map_disease_comprehensive(self, db_conn):
        """Test comprehensive disease mapping (EFO + MeSH)."""
        cursor = db_conn.cursor()

        # Test with both disease ID and MeSH
        result = map_disease_comprehensive(
            cursor,
            disease_id='EFO_0000400',
            mesh_ids=['C04.557.470']
        )

        assert isinstance(result, TAMappingResult)
        assert result.disease_id == 'EFO_0000400'

        # Should prefer EFO mapping over MeSH
        # (Will be UNKNOWN if EFO_0000400 not in mapping table)

    def test_map_disease_comprehensive_mesh_fallback(self, db_conn):
        """Test comprehensive mapping falls back to MeSH when EFO fails."""
        cursor = db_conn.cursor()

        result = map_disease_comprehensive(
            cursor,
            disease_id='EFO_9999999',  # Unmapped EFO
            mesh_ids=['C04.557.470']   # Cancer MeSH tree
        )

        # Should fall back to MeSH mapping
        assert result.primary_ta == TherapeuticArea.ONC
        assert result.disease_id == 'EFO_9999999'
        assert result.mesh_ids == ['C04.557.470']

    def test_ta_display_name(self):
        """Test TA display name retrieval."""
        assert get_ta_display_name(TherapeuticArea.ONC) == "Oncology"
        assert get_ta_display_name(TherapeuticArea.IMM) == "Immunology"
        assert get_ta_display_name(TherapeuticArea.CNS) == "Central Nervous System"
        assert get_ta_display_name(TherapeuticArea.UNKNOWN) == "Unknown"

    def test_validate_ta_code(self):
        """Test TA code validation."""
        # Valid codes
        assert validate_ta_code('ONC') is True
        assert validate_ta_code('IMM') is True
        assert validate_ta_code('UNKNOWN') is True

        # Invalid codes
        assert validate_ta_code('XXX') is False
        assert validate_ta_code('') is False
        assert validate_ta_code('onc') is False  # Case sensitive

    def test_ta_mapping_result_to_dict(self):
        """Test TAMappingResult serialization."""
        result = TAMappingResult(
            primary_ta=TherapeuticArea.ONC,
            all_tas=[TherapeuticArea.ONC, TherapeuticArea.RARE],
            disease_id='EFO_0001234',
            mesh_ids=['D009369'],
            mapping_source='mesh'
        )

        result_dict = result.to_dict()

        assert result_dict['primary_ta'] == 'ONC'
        assert result_dict['all_tas'] == ['ONC', 'RARE']
        assert result_dict['disease_id'] == 'EFO_0001234'
        assert result_dict['mesh_ids'] == ['D009369']
        assert result_dict['mapping_source'] == 'mesh'


# ============================================================================
# Integration Tests
# ============================================================================

class TestLiteratureNewsIntegration:
    """Integration tests for literature and news evidence."""

    @patch('biograph.integrations.pubmed.fetch_pubmed_article')
    def test_pubmed_evidence_with_ta_mapping(self, mock_fetch, db_conn):
        """Test creating PubMed evidence and mapping to TA."""
        # Mock PubMed article with MeSH IDs
        mock_fetch.return_value = {
            'pmid': '12345678',
            'title': 'Lung cancer study',
            'journal': 'Cancer Research',
            'publication_date': '2023-01-15',
            'doi': '10.1234/test',
            'mesh_ids': ['D008175', 'C04.588.894'],  # Lung neoplasms
            'url': 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
            'snippet': 'Lung cancer study'
        }

        cursor = db_conn.cursor()

        # Create evidence
        evidence_id = create_pubmed_evidence(cursor, '12345678')
        assert evidence_id is not None

        # Get MeSH IDs from article
        article = mock_fetch.return_value
        mesh_ids = article['mesh_ids']

        # Map to TA
        ta_result = map_mesh_to_ta(cursor, mesh_ids)

        # Should map to ONC (Oncology)
        assert ta_result.primary_ta == TherapeuticArea.ONC

        db_conn.rollback()

    def test_news_item_snippet_constraint(self, db_conn):
        """Test that news_item snippet is limited to 200 chars."""
        cursor = db_conn.cursor()

        # Try to insert news item with long snippet
        long_snippet = "A" * 250

        with pytest.raises(Exception):  # Should violate CHECK constraint
            cursor.execute("""
                INSERT INTO news_item (publisher, headline, published_at, url, snippet)
                VALUES (%s, %s, %s, %s, %s)
            """, ('Test Publisher', 'Test Headline', '2023-01-15', 'https://example.com/test', long_snippet))

        db_conn.rollback()

        # Valid snippet (200 chars) should work
        valid_snippet = "A" * 200

        cursor.execute("""
            INSERT INTO news_item (publisher, headline, published_at, url, snippet)
            VALUES (%s, %s, %s, %s, %s)
        """, ('Test Publisher', 'Test Headline', '2023-01-15', 'https://example.com/test2', valid_snippet))

        db_conn.rollback()

    def test_therapeutic_area_mapping_exists(self, db_conn):
        """Test that therapeutic_area_mapping table is prepopulated."""
        cursor = db_conn.cursor()

        # Should have prepopulated mappings
        cursor.execute("SELECT COUNT(*) FROM therapeutic_area_mapping")
        count = cursor.fetchone()[0]

        assert count > 0, "therapeutic_area_mapping should be prepopulated"

        # Check for expected TA codes
        cursor.execute("SELECT DISTINCT ta_code FROM therapeutic_area_mapping ORDER BY ta_code")
        ta_codes = [row[0] for row in cursor.fetchall()]

        # Should have at least some of the 8 TAs
        assert 'ONC' in ta_codes
        assert 'IMM' in ta_codes

    def test_ta_mapping_deterministic(self, db_conn):
        """Test that TA mapping is deterministic (same input → same output)."""
        cursor = db_conn.cursor()

        mesh_ids = ['C04.557.470']

        # Map twice
        result1 = map_mesh_to_ta(cursor, mesh_ids)
        result2 = map_mesh_to_ta(cursor, mesh_ids)

        # Should be identical
        assert result1.primary_ta == result2.primary_ta
        assert result1.all_tas == result2.all_tas
