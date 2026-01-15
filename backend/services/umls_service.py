#!/usr/bin/env python3
"""
UMLS Service - Medical terminology enrichment via UMLS API.

UMLS (Unified Medical Language System) integrates 200+ biomedical vocabularies:
- MeSH, SNOMED CT, ICD-10, RxNorm, LOINC, etc.
- Cross-mappings between terminologies
- Synonyms and definitions
- Semantic types

License: Free for research and commercial use (requires free UML license)
API Key: Get free API key at https://uts.nlm.nih.gov/uts/signup-login

Reference: https://www.nlm.nih.gov/research/umls/
API Docs: https://documentation.uts.nlm.nih.gov/rest/home.html
"""

import os
from typing import Dict, List, Optional
import requests
import time
from requests_cache import CachedSession

# UMLS REST API base URL
UMLS_BASE_URL = "https://uts-ws.nlm.nih.gov/rest"

class UMLSService:
    """
    Service for enriching medical entities via UMLS API.

    Features:
    - Medical term → CUI resolution
    - Cross-vocabulary mappings
    - Definitions and synonyms
    - Semantic types
    - Cached responses (7 days)

    Note: Requires UMLS API key (free at https://uts.nlm.nih.gov/uts/signup-login)
    Set UMLS_API_KEY environment variable.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("UMLS_API_KEY")

        if not self.api_key:
            print("⚠️  UMLS API key not found. Set UMLS_API_KEY environment variable.")
            print("   Get free key at: https://uts.nlm.nih.gov/uts/signup-login")
            print("   UMLS enrichment will be skipped.")

        # Use cached session (7 days for UMLS since it's more stable)
        self.session = CachedSession(
            'umls_cache',
            backend='sqlite',
            expire_after=604800  # 7 days
        )
        self.session.headers.update({
            "User-Agent": "BioGraph/1.0 (https://github.com/biograph)"
        })
        self.last_request_time = 0.0
        self.min_request_interval = 0.2  # 5 requests/second max

    def _rate_limit(self) -> None:
        """Rate limiting"""
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        self.last_request_time = time.time()

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make GET request with rate limiting and error handling"""
        if not self.api_key:
            return None

        try:
            self._rate_limit()
            url = f"{UMLS_BASE_URL}/{endpoint}"

            # Add API key to params
            params = params or {}
            params["apiKey"] = self.api_key

            response = self.session.get(url, params=params, timeout=10)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                print(f"UMLS API error: {response.status_code}")
                return None

        except Exception as e:
            print(f"UMLS request error: {e}")
            return None

    def search_concepts(self, term: str, limit: int = 5) -> List[Dict]:
        """
        Search for concepts by term.

        Args:
            term: Medical term to search
            limit: Maximum results

        Returns:
            List of concept dicts with cui, name, semantic_types
        """
        data = self._get("search/current", params={
            "string": term,
            "pageSize": limit,
            "returnIdType": "concept"
        })

        if not data or "result" not in data:
            return []

        concepts = []
        results = data["result"].get("results", [])

        for result in results:
            cui = result.get("ui")
            name = result.get("name")
            root_source = result.get("rootSource")

            if cui and name:
                concepts.append({
                    "cui": cui,
                    "name": name,
                    "root_source": root_source,
                })

        return concepts

    def get_concept_definition(self, cui: str) -> Optional[str]:
        """
        Get definition for a CUI.

        Args:
            cui: UMLS Concept Unique Identifier

        Returns:
            Definition text or None
        """
        data = self._get(f"content/current/CUI/{cui}/definitions")

        if not data or "result" not in data:
            return None

        results = data["result"]
        if results:
            # Return first definition (usually from most authoritative source)
            return results[0].get("value")

        return None

    def get_concept_synonyms(self, cui: str) -> List[str]:
        """
        Get synonyms for a CUI.

        Args:
            cui: UMLS Concept Unique Identifier

        Returns:
            List of synonym strings
        """
        # Get atoms (terms) for this concept
        data = self._get(f"content/current/CUI/{cui}/atoms")

        if not data or "result" not in data:
            return []

        synonyms = set()
        for atom in data["result"]:
            name = atom.get("name")
            if name:
                synonyms.add(name)

        return list(synonyms)

    def get_concept_semantic_types(self, cui: str) -> List[str]:
        """
        Get semantic types for a CUI.

        Args:
            cui: UMLS Concept Unique Identifier

        Returns:
            List of semantic type strings (e.g., "Disease or Syndrome", "Pharmacologic Substance")
        """
        data = self._get(f"content/current/CUI/{cui}")

        if not data or "result" not in data:
            return []

        semantic_types = []
        result = data["result"]

        for sem_type in result.get("semanticTypes", []):
            name = sem_type.get("name")
            if name:
                semantic_types.append(name)

        return semantic_types

    def get_mesh_mapping(self, cui: str) -> Optional[str]:
        """
        Get MeSH ID for a UMLS CUI.

        Args:
            cui: UMLS CUI

        Returns:
            MeSH descriptor ID (e.g., 'D009765') or None
        """
        # Get atoms with source = MSH (MeSH)
        data = self._get(f"content/current/CUI/{cui}/atoms", params={"sabs": "MSH"})

        if not data or "result" not in data:
            return None

        for atom in data["result"]:
            # Look for MSH code in sourceConceptIdList
            code = atom.get("code")
            if code and code.startswith("D"):  # MeSH descriptors start with D
                return code

        return None

    def enrich_medical_term(self, term: str) -> Optional[Dict]:
        """
        Complete enrichment for a medical term.

        Args:
            term: Medical term (disease, drug, symptom, etc.)

        Returns:
            Dict with enrichment data or None if not found
        """
        # Search for concept
        concepts = self.search_concepts(term, limit=1)

        if not concepts:
            return None

        cui = concepts[0]["cui"]
        name = concepts[0]["name"]

        # Get definition
        definition = self.get_concept_definition(cui)

        # Get synonyms
        synonyms = self.get_concept_synonyms(cui)

        # Get semantic types
        semantic_types = self.get_concept_semantic_types(cui)

        # Get MeSH mapping
        mesh_id = self.get_mesh_mapping(cui)

        return {
            "cui": cui,
            "name": name,
            "description": definition,
            "synonyms": synonyms[:20],  # Limit to first 20
            "semantic_types": semantic_types,
            "mesh_id": mesh_id,
            "source": "umls"
        }

# Global singleton
_umls_service: Optional[UMLSService] = None

def get_umls_service() -> UMLSService:
    """Get global UMLS service instance"""
    global _umls_service
    if _umls_service is None:
        _umls_service = UMLSService()
    return _umls_service

# Example usage
if __name__ == "__main__":
    service = get_umls_service()

    if not service.api_key:
        print("Set UMLS_API_KEY to test")
        exit(1)

    print("=== Testing Diabetes ===")
    result = service.enrich_medical_term("Diabetes Mellitus")
    if result:
        print(f"CUI: {result['cui']}")
        print(f"Name: {result['name']}")
        print(f"Definition: {result['description'][:200]}...")
        print(f"Semantic Types: {result['semantic_types']}")
        print(f"MeSH ID: {result['mesh_id']}")
        print(f"Synonyms: {result['synonyms'][:5]}")
