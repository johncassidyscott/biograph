#!/usr/bin/env python3
"""
Wikidata Service - Entity enrichment via Wikidata's knowledge graph.

Wikidata is the world's largest open knowledge base with:
- 100M+ entities
- Multilingual coverage
- External identifier links (LEI, PermID, OpenCorporates, etc.)
- CC0 public domain license

This service queries Wikidata's SPARQL endpoint to enrich entities with:
- Descriptions
- External identifiers (LEI, PermID, OpenCorporates, stock tickers)
- Alternative names
- Industry classifications
- Relationships

Reference: https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service
"""

from typing import Dict, List, Optional, Tuple
from SPARQLWrapper import SPARQLWrapper, JSON
import time
import requests_cache

# Install cache to avoid hammering Wikidata (they're free, be nice)
requests_cache.install_cache('wikidata_cache', backend='sqlite', expire_after=86400)  # 24hr cache

# Wikidata SPARQL endpoint
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"

# User agent (Wikidata requires identification)
USER_AGENT = "BioGraph/1.0 (https://github.com/biograph; [email protected]) Python/SPARQLWrapper"

class WikidataService:
    """
    Service for querying Wikidata to enrich entities.

    Features:
    - Automatic rate limiting (1 req/sec to be nice)
    - Response caching (24hr)
    - Robust error handling
    - Batch queries where possible
    """

    def __init__(self):
        self.sparql = SPARQLWrapper(WIKIDATA_ENDPOINT)
        self.sparql.setReturnFormat(JSON)
        self.sparql.addCustomHttpHeader("User-Agent", USER_AGENT)
        self.last_request_time = 0.0
        self.min_request_interval = 1.0  # 1 second between requests

    def _rate_limit(self) -> None:
        """Ensure we don't exceed 1 request/second"""
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        self.last_request_time = time.time()

    def _query(self, sparql_query: str) -> List[Dict]:
        """Execute SPARQL query with rate limiting and error handling"""
        try:
            self._rate_limit()
            self.sparql.setQuery(sparql_query)
            results = self.sparql.query().convert()
            return results.get("results", {}).get("bindings", [])
        except Exception as e:
            print(f"Wikidata query error: {e}")
            return []

    def search_entity(
        self,
        name: str,
        entity_type: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict]:
        """
        Search for entities by name.

        Args:
            name: Entity name to search
            entity_type: Optional filter ('company', 'drug', 'disease', 'person')
            limit: Maximum results

        Returns:
            List of dicts with keys: qid, label, description, type
        """
        # Map our types to Wikidata instance types
        type_filters = {
            "company": "wd:Q4830453",  # Business enterprise
            "drug": "wd:Q12140",  # Medication
            "disease": "wd:Q12136",  # Disease
            "person": "wd:Q5",  # Human
            "target": "wd:Q8054",  # Protein
        }

        type_clause = ""
        if entity_type and entity_type in type_filters:
            type_clause = f"?item wdt:P31/wdt:P279* {type_filters[entity_type]} ."

        query = f"""
        SELECT ?item ?itemLabel ?itemDescription ?typeLabel WHERE {{
          ?item rdfs:label "{name}"@en .
          {type_clause}
          OPTIONAL {{ ?item wdt:P31 ?type }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }}
        LIMIT {limit}
        """

        results = self._query(query)

        entities = []
        for result in results:
            qid = result.get("item", {}).get("value", "").split("/")[-1]
            label = result.get("itemLabel", {}).get("value", "")
            description = result.get("itemDescription", {}).get("value", "")
            entity_type_label = result.get("typeLabel", {}).get("value", "")

            if qid:
                entities.append({
                    "qid": qid,
                    "label": label,
                    "description": description,
                    "type": entity_type_label
                })

        return entities

    def get_entity_identifiers(self, qid: str) -> Dict[str, str]:
        """
        Get all external identifiers for a Wikidata entity.

        Args:
            qid: Wikidata QID (e.g., 'Q30715381' for Moderna)

        Returns:
            Dict mapping identifier types to values:
            {
                'lei': '549300RHD38RQKER3658',
                'permid': '5000168508',
                'opencorporates': 'us_de/4389449',
                'sec_cik': '0001682852',
                'ticker': 'MRNA'
            }
        """
        # Wikidata property IDs for external identifiers
        property_map = {
            "lei": "P1278",  # Legal Entity Identifier
            "permid": "P3347",  # PermID
            "opencorporates": "P1320",  # OpenCorporates ID
            "sec_cik": "P5531",  # SEC CIK
            "ticker": "P249",  # Stock ticker (NASDAQ/NYSE)
            "naics": "P1423",  # NAICS code
            "sic": "P1424",  # SIC code
            "mesh": "P486",  # MeSH ID
            "chembl": "P592",  # ChEMBL ID
            "pubchem": "P662",  # PubChem CID
            "uniprot": "P352",  # UniProt ID (for proteins/targets)
            "official_website": "P856",
            "wikipedia": "P1151",
        }

        query = f"""
        SELECT ?prop ?propLabel ?value WHERE {{
          wd:{qid} ?prop ?value .
          FILTER(?prop IN ({", ".join(f"wdt:{pid}" for pid in property_map.values())}))
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }}
        """

        results = self._query(query)

        identifiers = {}
        reverse_map = {pid: name for name, pid in property_map.items()}

        for result in results:
            prop_uri = result.get("prop", {}).get("value", "")
            value = result.get("value", {}).get("value", "")

            # Extract property ID from URI
            prop_id = prop_uri.split("/")[-1]

            if prop_id in reverse_map and value:
                identifier_type = reverse_map[prop_id]
                identifiers[identifier_type] = value

        return identifiers

    def get_entity_description(self, qid: str) -> Optional[str]:
        """
        Get entity description from Wikidata.

        Args:
            qid: Wikidata QID

        Returns:
            English description or None
        """
        query = f"""
        SELECT ?description WHERE {{
          wd:{qid} schema:description ?description .
          FILTER(LANG(?description) = "en")
        }}
        LIMIT 1
        """

        results = self._query(query)

        if results:
            return results[0].get("description", {}).get("value")

        return None

    def get_entity_aliases(self, qid: str) -> List[str]:
        """
        Get alternative names for an entity.

        Args:
            qid: Wikidata QID

        Returns:
            List of alias strings
        """
        query = f"""
        SELECT ?alias WHERE {{
          wd:{qid} skos:altLabel ?alias .
          FILTER(LANG(?alias) = "en")
        }}
        """

        results = self._query(query)
        return [r.get("alias", {}).get("value", "") for r in results if r.get("alias")]

    def enrich_company(self, company_name: str) -> Optional[Dict]:
        """
        Complete enrichment for a company entity.

        Args:
            company_name: Company name to enrich

        Returns:
            Dict with enrichment data or None if not found
        """
        # Search for company
        entities = self.search_entity(company_name, entity_type="company", limit=1)

        if not entities:
            return None

        qid = entities[0]["qid"]
        description = entities[0]["description"]

        # Get identifiers
        identifiers = self.get_entity_identifiers(qid)

        # Get aliases
        aliases = self.get_entity_aliases(qid)

        return {
            "qid": qid,
            "description": description,
            "identifiers": identifiers,
            "aliases": aliases,
            "source": "wikidata"
        }

    def enrich_drug(self, drug_name: str) -> Optional[Dict]:
        """Complete enrichment for a drug entity"""
        entities = self.search_entity(drug_name, entity_type="drug", limit=1)

        if not entities:
            return None

        qid = entities[0]["qid"]
        description = entities[0]["description"]
        identifiers = self.get_entity_identifiers(qid)
        aliases = self.get_entity_aliases(qid)

        return {
            "qid": qid,
            "description": description,
            "identifiers": identifiers,
            "aliases": aliases,
            "source": "wikidata"
        }

    def enrich_disease(self, disease_name: str) -> Optional[Dict]:
        """Complete enrichment for a disease entity"""
        entities = self.search_entity(disease_name, entity_type="disease", limit=1)

        if not entities:
            return None

        qid = entities[0]["qid"]
        description = entities[0]["description"]
        identifiers = self.get_entity_identifiers(qid)
        aliases = self.get_entity_aliases(qid)

        return {
            "qid": qid,
            "description": description,
            "identifiers": identifiers,
            "aliases": aliases,
            "source": "wikidata"
        }

# Global singleton
_wikidata_service: Optional[WikidataService] = None

def get_wikidata_service() -> WikidataService:
    """Get global Wikidata service instance"""
    global _wikidata_service
    if _wikidata_service is None:
        _wikidata_service = WikidataService()
    return _wikidata_service

# Example usage
if __name__ == "__main__":
    service = get_wikidata_service()

    print("=== Testing Moderna Inc ===")
    result = service.enrich_company("Moderna Inc")
    if result:
        print(f"QID: {result['qid']}")
        print(f"Description: {result['description']}")
        print(f"Identifiers: {result['identifiers']}")
        print(f"Aliases: {result['aliases'][:5]}")  # First 5 aliases

    print("\n=== Testing Ibuprofen ===")
    result = service.enrich_drug("Ibuprofen")
    if result:
        print(f"QID: {result['qid']}")
        print(f"Description: {result['description']}")
        print(f"Identifiers: {result['identifiers']}")
