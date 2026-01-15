"""
BioGraph Services - State-of-the-art entity enrichment and resolution.

This package provides industry-standard entity resolution using:
- Semantic embeddings (SapBERT, PubMedBERT)
- Knowledge base integration (Wikidata, UMLS, ChEMBL)
- Vector similarity search (pgvector)

Services:
- embedding_service: Generate semantic embeddings for entity matching
- wikidata_service: Enrich entities with Wikidata identifiers and descriptions
- chembl_service: Enrich drug entities with ChEMBL data
- umls_service: Enrich medical terms with UMLS vocabulary mappings
"""

from .embedding_service import get_embedding_service, EmbeddingService
from .wikidata_service import get_wikidata_service, WikidataService
from .chembl_service import get_chembl_service, ChEMBLService
from .umls_service import get_umls_service, UMLSService

__all__ = [
    "get_embedding_service",
    "EmbeddingService",
    "get_wikidata_service",
    "WikidataService",
    "get_chembl_service",
    "ChEMBLService",
    "get_umls_service",
    "UMLSService",
]
