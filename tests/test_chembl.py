"""
Unit tests for ChEMBL Integration (Section 23C.2).

Tests for drug-target interactions, mechanisms, indications, and import functionality.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from biograph.integrations.chembl import (
    fetch_molecule_live,
    fetch_drug_mechanisms,
    fetch_drug_targets,
    fetch_drug_indications,
    fetch_comprehensive_drug_data,
    validate_chembl_id,
    get_chembl_label,
    create_chembl_evidence,
    create_drug_target_assertion,
    create_drug_indication_assertion,
    search_chembl_molecules,
    DrugIndication,
    CHEMBL_LICENSE
)


class TestChEMBLValidation:
    """Test ChEMBL ID validation."""

    def test_validate_chembl_id_valid(self):
        """Test valid ChEMBL IDs."""
        assert validate_chembl_id('CHEMBL25') is True
        assert validate_chembl_id('CHEMBL1201234') is True
        assert validate_chembl_id('CHEMBL1') is True

    def test_validate_chembl_id_invalid(self):
        """Test invalid ChEMBL IDs."""
        assert validate_chembl_id('CHEMBL') is False  # No number
        assert validate_chembl_id('chembl25') is False  # Lowercase
        assert validate_chembl_id('CHEM25') is False  # Wrong prefix
        assert validate_chembl_id('CHEMBL-25') is False  # Dash
        assert validate_chembl_id('') is False  # Empty


class TestMoleculeResolution:
    """Test molecule label resolution."""

    @patch('biograph.integrations.chembl.requests.get')
    def test_fetch_molecule_live_success(self, mock_get):
        """Test successful molecule fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "molecule_chembl_id": "CHEMBL25",
            "pref_name": "ASPIRIN",
            "molecule_type": "Small molecule",
            "max_phase": 4
        }
        mock_get.return_value = mock_response

        result = fetch_molecule_live('CHEMBL25')

        assert result is not None
        assert result['id'] == 'CHEMBL25'
        assert result['label'] == 'ASPIRIN'
        assert result['molecule_type'] == 'Small molecule'
        assert result['max_phase'] == 4
        assert result['source'] == 'chembl'

    @patch('biograph.integrations.chembl.requests.get')
    def test_fetch_molecule_live_not_found(self, mock_get):
        """Test molecule not found."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = fetch_molecule_live('CHEMBL999999999')

        assert result is None

    @patch('biograph.integrations.chembl.requests.get')
    def test_fetch_molecule_live_timeout(self, mock_get):
        """Test timeout handling."""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()

        result = fetch_molecule_live('CHEMBL25')

        assert result is None


class TestDrugMechanisms:
    """Test drug mechanism of action fetching."""

    @patch('biograph.integrations.chembl.requests.get')
    def test_fetch_drug_mechanisms_success(self, mock_get):
        """Test successful mechanism fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "mechanisms": [
                {
                    "target_chembl_id": "CHEMBL2083",
                    "target_name": "Cyclooxygenase-2",
                    "mechanism_of_action": "Cyclooxygenase inhibitor",
                    "action_type": "INHIBITOR",
                    "max_phase": 4,
                    "molecule_chembl_id": "CHEMBL25"
                }
            ]
        }
        mock_get.return_value = mock_response

        result = fetch_drug_mechanisms('CHEMBL25')

        assert len(result) == 1
        assert result[0]['target_chembl_id'] == 'CHEMBL2083'
        assert result[0]['action_type'] == 'INHIBITOR'

    @patch('biograph.integrations.chembl.requests.get')
    def test_fetch_drug_mechanisms_none(self, mock_get):
        """Test molecule with no mechanisms."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"mechanisms": []}
        mock_get.return_value = mock_response

        result = fetch_drug_mechanisms('CHEMBL12345')

        assert result == []


class TestDrugTargets:
    """Test drug-target interaction fetching."""

    @patch('biograph.integrations.chembl.requests.get')
    def test_fetch_drug_targets_success(self, mock_get):
        """Test successful target activity fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "activities": [
                {
                    "target_chembl_id": "CHEMBL2083",
                    "target_pref_name": "Cyclooxygenase-2",
                    "target_type": "SINGLE PROTEIN",
                    "standard_type": "IC50",
                    "standard_value": 0.5,
                    "standard_units": "nM",
                    "pchembl_value": 9.3,
                    "assay_chembl_id": "CHEMBL12345",
                    "document_chembl_id": "CHEMBL67890"
                }
            ]
        }
        mock_get.return_value = mock_response

        result = fetch_drug_targets('CHEMBL25')

        assert len(result) == 1
        assert result[0]['target_chembl_id'] == 'CHEMBL2083'
        assert result[0]['pchembl_value'] == 9.3

    @patch('biograph.integrations.chembl.requests.get')
    def test_fetch_drug_targets_keeps_best_activity(self, mock_get):
        """Test that best activity is kept for each target."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "activities": [
                {
                    "target_chembl_id": "CHEMBL2083",
                    "target_pref_name": "COX-2",
                    "pchembl_value": 7.0,
                    "standard_type": "IC50"
                },
                {
                    "target_chembl_id": "CHEMBL2083",
                    "target_pref_name": "COX-2",
                    "pchembl_value": 9.0,  # Better activity
                    "standard_type": "IC50"
                }
            ]
        }
        mock_get.return_value = mock_response

        result = fetch_drug_targets('CHEMBL25')

        assert len(result) == 1
        assert result[0]['pchembl_value'] == 9.0  # Best activity kept


class TestDrugIndications:
    """Test drug indication (disease) fetching."""

    @patch('biograph.integrations.chembl.fetch_molecule_live')
    @patch('biograph.integrations.chembl.requests.get')
    def test_fetch_drug_indications_success(self, mock_get, mock_molecule):
        """Test successful indication fetch."""
        mock_molecule.return_value = {"label": "Aspirin"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "drug_indications": [
                {
                    "mesh_heading": "Pain",
                    "mesh_id": "D010146",
                    "efo_id": "EFO_0003843",
                    "max_phase_for_ind": 4,
                    "indication_refs": [{"ref_url": "http://example.com"}]
                }
            ]
        }
        mock_get.return_value = mock_response

        result = fetch_drug_indications('CHEMBL25')

        assert len(result) == 1
        assert isinstance(result[0], DrugIndication)
        assert result[0].indication_name == 'Pain'
        assert result[0].mesh_id == 'D010146'
        assert result[0].max_phase_for_ind == 4


class TestComprehensiveData:
    """Test comprehensive drug data fetching."""

    @patch('biograph.integrations.chembl.fetch_drug_indications')
    @patch('biograph.integrations.chembl.fetch_drug_targets')
    @patch('biograph.integrations.chembl.fetch_drug_mechanisms')
    @patch('biograph.integrations.chembl.fetch_molecule_live')
    def test_fetch_comprehensive_drug_data(
        self, mock_molecule, mock_mechs, mock_targets, mock_indications
    ):
        """Test comprehensive data aggregation."""
        mock_molecule.return_value = {"id": "CHEMBL25", "label": "ASPIRIN"}
        mock_mechs.return_value = [{"target_chembl_id": "CHEMBL2083"}]
        mock_targets.return_value = [{"target_chembl_id": "CHEMBL2083"}]
        mock_indications.return_value = [
            DrugIndication("CHEMBL25", "ASPIRIN", "Pain", "D010146", None, 4, [])
        ]

        result = fetch_comprehensive_drug_data('CHEMBL25')

        assert result['molecule'] is not None
        assert len(result['mechanisms']) == 1
        assert len(result['targets']) == 1
        assert len(result['indications']) == 1
        assert 'fetched_at' in result

    def test_fetch_comprehensive_drug_data_invalid_id(self):
        """Test with invalid ChEMBL ID."""
        with pytest.raises(ValueError, match="Invalid ChEMBL ID"):
            fetch_comprehensive_drug_data('INVALID123')


class TestEvidenceCreation:
    """Test evidence creation from ChEMBL data."""

    def test_create_chembl_evidence(self, db_conn):
        """Test creating evidence from ChEMBL."""
        cursor = db_conn.cursor()

        # Create batch operation first
        cursor.execute("""
            INSERT INTO batch_operation (batch_id, operation_type, status)
            VALUES ('chembl_test_batch', 'chembl_import', 'running')
        """)

        evidence_id = create_chembl_evidence(
            cursor=cursor,
            chembl_id='CHEMBL25',
            source_record_type='mechanism',
            source_record_id='CHEMBL2083',
            snippet='Aspirin inhibits COX-2',
            batch_id='chembl_test_batch'
        )

        assert evidence_id > 0

        # Verify evidence
        cursor.execute("""
            SELECT source_system, license, snippet
            FROM evidence WHERE evidence_id = %s
        """, (evidence_id,))

        row = cursor.fetchone()
        assert row[0] == 'chembl'
        assert row[1] == CHEMBL_LICENSE
        assert 'Aspirin' in row[2]

        db_conn.rollback()

    def test_create_chembl_evidence_duplicate(self, db_conn):
        """Test that duplicate evidence returns existing ID."""
        cursor = db_conn.cursor()

        # Create batch operation first
        cursor.execute("""
            INSERT INTO batch_operation (batch_id, operation_type, status)
            VALUES ('chembl_dup_batch', 'chembl_import', 'running')
        """)

        # Create first evidence
        evidence_id_1 = create_chembl_evidence(
            cursor, 'CHEMBL25', 'mechanism', 'CHEMBL2083',
            'Aspirin inhibits COX-2', 'chembl_dup_batch'
        )

        # Create duplicate
        evidence_id_2 = create_chembl_evidence(
            cursor, 'CHEMBL25', 'mechanism', 'CHEMBL2083',
            'Different snippet', 'chembl_dup_batch'
        )

        assert evidence_id_1 == evidence_id_2

        db_conn.rollback()


class TestAssertionCreation:
    """Test assertion creation from ChEMBL data."""

    def test_create_drug_target_assertion(self, db_conn):
        """Test creating drug-target assertion."""
        cursor = db_conn.cursor()

        # Create prerequisites
        cursor.execute("""
            INSERT INTO issuer (issuer_id, primary_cik)
            VALUES ('ISS_CHEMBL_TEST', '0000000001')
        """)
        cursor.execute("""
            INSERT INTO drug_program (drug_program_id, issuer_id, slug, name)
            VALUES ('CIK:0000000001:PROG:aspirin', 'ISS_CHEMBL_TEST', 'aspirin', 'Aspirin')
        """)
        cursor.execute("""
            INSERT INTO target (target_id, name)
            VALUES ('CHEMBL2083', 'COX-2')
        """)
        cursor.execute("""
            INSERT INTO batch_operation (batch_id, operation_type, status)
            VALUES ('assert_batch', 'chembl_import', 'running')
        """)
        cursor.execute("""
            INSERT INTO evidence (source_system, source_record_id, observed_at, license, uri)
            VALUES ('chembl', 'test_record', NOW(), 'CC-BY-SA-3.0', 'http://test.com')
            RETURNING evidence_id
        """)
        evidence_id = cursor.fetchone()[0]

        assertion_id = create_drug_target_assertion(
            cursor=cursor,
            drug_program_id='CIK:0000000001:PROG:aspirin',
            target_id='CHEMBL2083',
            evidence_id=evidence_id,
            mechanism='Cyclooxygenase inhibitor',
            action_type='INHIBITOR'
        )

        assert assertion_id > 0

        # Verify assertion
        cursor.execute("""
            SELECT predicate, link_rationale_json FROM assertion WHERE assertion_id = %s
        """, (assertion_id,))

        row = cursor.fetchone()
        assert row[0] == 'inhibits'  # Action type maps to predicate
        assert row[1]['mechanism'] == 'Cyclooxygenase inhibitor'

        db_conn.rollback()

    def test_create_drug_indication_assertion_phase4(self, db_conn):
        """Test creating drug-indication assertion for approved drug."""
        cursor = db_conn.cursor()

        # Create prerequisites
        cursor.execute("""
            INSERT INTO issuer (issuer_id, primary_cik)
            VALUES ('ISS_IND_TEST', '0000000002')
        """)
        cursor.execute("""
            INSERT INTO drug_program (drug_program_id, issuer_id, slug, name)
            VALUES ('CIK:0000000002:PROG:drug1', 'ISS_IND_TEST', 'drug1', 'Drug 1')
        """)
        cursor.execute("""
            INSERT INTO disease (disease_id, name)
            VALUES ('EFO_0003843', 'Pain')
        """)
        cursor.execute("""
            INSERT INTO evidence (source_system, source_record_id, observed_at, license, uri)
            VALUES ('chembl', 'indication_record', NOW(), 'CC-BY-SA-3.0', 'http://test.com')
            RETURNING evidence_id
        """)
        evidence_id = cursor.fetchone()[0]

        assertion_id = create_drug_indication_assertion(
            cursor=cursor,
            drug_program_id='CIK:0000000002:PROG:drug1',
            disease_id='EFO_0003843',
            evidence_id=evidence_id,
            max_phase=4
        )

        # Verify predicate reflects approval
        cursor.execute("""
            SELECT predicate FROM assertion WHERE assertion_id = %s
        """, (assertion_id,))

        assert cursor.fetchone()[0] == 'approved_for'

        db_conn.rollback()


class TestChEMBLSearch:
    """Test ChEMBL search functionality."""

    @patch('biograph.integrations.chembl.requests.get')
    def test_search_chembl_molecules(self, mock_get):
        """Test molecule search."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "molecules": [
                {
                    "molecule_chembl_id": "CHEMBL25",
                    "pref_name": "ASPIRIN",
                    "molecule_type": "Small molecule",
                    "max_phase": 4
                },
                {
                    "molecule_chembl_id": "CHEMBL1",
                    "pref_name": "ACETYLSALICYLIC ACID",
                    "molecule_type": "Small molecule",
                    "max_phase": 4
                }
            ]
        }
        mock_get.return_value = mock_response

        results = search_chembl_molecules('aspirin')

        assert len(results) == 2
        assert results[0]['chembl_id'] == 'CHEMBL25'
        assert results[0]['pref_name'] == 'ASPIRIN'


class TestChEMBLLabelResolution:
    """Test ChEMBL label resolution with caching."""

    @patch('biograph.integrations.chembl.cached_resolve_with_fallback')
    def test_get_chembl_label_cached(self, mock_cached_resolve, db_conn):
        """Test label retrieval uses cache."""
        mock_cached_resolve.return_value = {
            'id': 'CHEMBL25',
            'label': 'ASPIRIN',
            'source': 'chembl'
        }

        cursor = db_conn.cursor()
        result = get_chembl_label(cursor, 'CHEMBL25')

        assert result['label'] == 'ASPIRIN'
        mock_cached_resolve.assert_called_once()


class TestChEMBLLicenseValid:
    """Test that ChEMBL license is in allowlist."""

    def test_chembl_license_in_allowlist(self, db_conn):
        """Verify ChEMBL license is in the license allowlist."""
        cursor = db_conn.cursor()

        cursor.execute("""
            SELECT 1 FROM license_allowlist WHERE license = %s
        """, (CHEMBL_LICENSE,))

        assert cursor.fetchone() is not None, f"ChEMBL license {CHEMBL_LICENSE} not in allowlist"
