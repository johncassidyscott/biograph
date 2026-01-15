#!/usr/bin/env python3
"""
ChEMBL Service - Drug entity enrichment via ChEMBL REST API.

ChEMBL is the gold standard for bioactive drug-like molecules:
- 2.4M+ compounds
- 18M+ bioactivity measurements
- Target/mechanism data
- Clinical trial information
- Free REST API (no authentication required)

License: CC BY-SA 3.0 (compatible with commercial use with attribution)

Reference: https://www.ebi.ac.uk/chembl/
API Docs: https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services
"""

from typing import Dict, List, Optional
import requests
import time
from requests_cache import CachedSession

# ChEMBL REST API base URL
CHEMBL_BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"

class ChEMBLService:
    """
    Service for enriching drug entities via ChEMBL API.

    Features:
    - Drug name → ChEMBL ID resolution
    - Molecular structure, properties
    - Clinical trial phase information
    - Target mechanism data
    - Cached responses (24hr)
    """

    def __init__(self):
        # Use cached session to avoid repeated API calls
        self.session = CachedSession(
            'chembl_cache',
            backend='sqlite',
            expire_after=86400  # 24 hours
        )
        self.session.headers.update({
            "User-Agent": "BioGraph/1.0 (https://github.com/biograph)"
        })
        self.last_request_time = 0.0
        self.min_request_interval = 0.2  # 5 requests/second max

    def _rate_limit(self) -> None:
        """Rate limiting to be nice to EBI servers"""
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        self.last_request_time = time.time()

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make GET request with rate limiting and error handling"""
        try:
            self._rate_limit()
            url = f"{CHEMBL_BASE_URL}/{endpoint}.json"
            response = self.session.get(url, params=params, timeout=10)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                print(f"ChEMBL API error: {response.status_code}")
                return None

        except Exception as e:
            print(f"ChEMBL request error: {e}")
            return None

    def search_molecule(self, name: str, limit: int = 5) -> List[Dict]:
        """
        Search for molecules by name.

        Args:
            name: Drug/molecule name
            limit: Maximum results

        Returns:
            List of molecule dicts with chembl_id, pref_name, max_phase
        """
        data = self._get("molecule", params={"molecule_synonyms__icontains": name, "limit": limit})

        if not data or "molecules" not in data:
            return []

        molecules = []
        for mol in data["molecules"]:
            molecules.append({
                "chembl_id": mol.get("molecule_chembl_id"),
                "pref_name": mol.get("pref_name"),
                "max_phase": mol.get("max_phase"),  # Clinical trial phase (0-4)
                "molecule_type": mol.get("molecule_type"),
                "first_approval": mol.get("first_approval"),
                "oral": mol.get("oral"),
                "parenteral": mol.get("parenteral"),
                "topical": mol.get("topical"),
            })

        return molecules

    def get_molecule_by_id(self, chembl_id: str) -> Optional[Dict]:
        """
        Get complete molecule information by ChEMBL ID.

        Args:
            chembl_id: ChEMBL ID (e.g., 'CHEMBL25' for aspirin)

        Returns:
            Dict with molecule details
        """
        data = self._get(f"molecule/{chembl_id}")

        if not data:
            return None

        return data

    def get_molecule_mechanisms(self, chembl_id: str) -> List[Dict]:
        """
        Get mechanism of action for a drug.

        Args:
            chembl_id: ChEMBL ID

        Returns:
            List of mechanism dicts with target, action_type, mechanism
        """
        data = self._get("mechanism", params={"molecule_chembl_id": chembl_id})

        if not data or "mechanisms" not in data:
            return []

        mechanisms = []
        for mech in data["mechanisms"]:
            mechanisms.append({
                "target_chembl_id": mech.get("target_chembl_id"),
                "target_name": mech.get("target_name"),
                "action_type": mech.get("action_type"),
                "mechanism_of_action": mech.get("mechanism_of_action"),
            })

        return mechanisms

    def enrich_drug(self, drug_name: str) -> Optional[Dict]:
        """
        Complete enrichment for a drug.

        Args:
            drug_name: Drug name

        Returns:
            Dict with enrichment data or None if not found
        """
        # Search for molecule
        molecules = self.search_molecule(drug_name, limit=1)

        if not molecules:
            return None

        chembl_id = molecules[0]["chembl_id"]

        # Get full details
        details = self.get_molecule_by_id(chembl_id)

        if not details:
            return None

        # Get mechanisms
        mechanisms = self.get_molecule_mechanisms(chembl_id)

        # Extract key info
        mol_data = details
        pref_name = mol_data.get("pref_name", drug_name)
        description = mol_data.get("molecule_properties", {}).get("full_mwt", "")

        # Build description
        max_phase = mol_data.get("max_phase")
        phase_text = {
            0: "Preclinical",
            1: "Phase 1",
            2: "Phase 2",
            3: "Phase 3",
            4: "Approved"
        }.get(max_phase, "Unknown phase")

        description = f"{pref_name}. Max clinical phase: {phase_text}."

        if mechanisms:
            mech_text = mechanisms[0].get("mechanism_of_action")
            if mech_text:
                description += f" Mechanism: {mech_text}."

        # Get synonyms
        synonyms = [syn.get("molecule_synonym") for syn in mol_data.get("molecule_synonyms", []) if syn.get("molecule_synonym")]

        return {
            "chembl_id": chembl_id,
            "pref_name": pref_name,
            "description": description,
            "max_phase": max_phase,
            "first_approval": mol_data.get("first_approval"),
            "molecule_type": mol_data.get("molecule_type"),
            "mechanisms": mechanisms,
            "synonyms": synonyms[:10],  # Limit to first 10
            "properties": mol_data.get("molecule_properties", {}),
            "source": "chembl"
        }

# Global singleton
_chembl_service: Optional[ChEMBLService] = None

def get_chembl_service() -> ChEMBLService:
    """Get global ChEMBL service instance"""
    global _chembl_service
    if _chembl_service is None:
        _chembl_service = ChEMBLService()
    return _chembl_service

# Example usage
if __name__ == "__main__":
    service = get_chembl_service()

    print("=== Testing Ibuprofen ===")
    result = service.enrich_drug("Ibuprofen")
    if result:
        print(f"ChEMBL ID: {result['chembl_id']}")
        print(f"Pref Name: {result['pref_name']}")
        print(f"Description: {result['description']}")
        print(f"Max Phase: {result['max_phase']}")
        print(f"Mechanisms: {len(result['mechanisms'])}")
        print(f"Synonyms: {result['synonyms'][:3]}")

    print("\n=== Testing Aspirin ===")
    result = service.enrich_drug("Aspirin")
    if result:
        print(f"ChEMBL ID: {result['chembl_id']}")
        print(f"Description: {result['description']}")
