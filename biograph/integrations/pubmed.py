"""
BioGraph MVP v8.2 - PubMed Resolver

Per Section 24A of the spec, this module fetches PubMed article METADATA ONLY
(no full text) using NLM E-utilities API.

Storage Strategy (Metadata-Only):
- PMID (PubMed ID)
- title
- journal
- publication_date
- MeSH IDs
- DOI (if present)
- PubMed URL

FORBIDDEN:
- Full text extraction
- PDF downloads
- Abstract text (except max 200 char snippet)

Evidence Creation:
- source_system = 'pubmed'
- source_record_id = PMID
- license = 'NLM_PUBLIC'
- snippet = title (max 200 chars)

ASSERTION SUPPORT RULE (LOCKED):
PubMed evidence may SUPPORT assertions but may NEVER be the sole evidence.
"""

from typing import Any, Dict, Optional, List
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

logger = logging.getLogger(__name__)

# NLM E-utilities API
EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Query timeout (seconds)
REQUEST_TIMEOUT = 15


def fetch_pubmed_article(pmid: str) -> Optional[Dict[str, Any]]:
    """
    Fetch PubMed article metadata using E-utilities API.

    Fetches:
    - PMID
    - Article Title
    - Journal
    - Publication Date
    - MeSH IDs
    - DOI (if present)

    Args:
        pmid: PubMed ID (e.g., '12345678')

    Returns:
        Dict with article metadata, or None on failure
    """
    try:
        logger.debug(f"Fetching PubMed article: {pmid}")

        # Use efetch to get article details
        url = f"{EUTILS_BASE_URL}/efetch.fcgi"
        params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "xml"
        }

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

        if response.status_code == 404:
            logger.warning(f"PubMed article not found: {pmid}")
            return None

        response.raise_for_status()

        # Parse XML response
        root = ET.fromstring(response.content)

        # Find the PubmedArticle element
        article = root.find(".//PubmedArticle")
        if article is None:
            logger.warning(f"No PubmedArticle found for PMID {pmid}")
            return None

        # Extract title
        title_elem = article.find(".//ArticleTitle")
        title = title_elem.text if title_elem is not None else None

        # Extract journal
        journal_elem = article.find(".//Journal/Title")
        journal = journal_elem.text if journal_elem is not None else None

        # Extract publication date
        pub_date = None
        pub_date_elem = article.find(".//PubDate")
        if pub_date_elem is not None:
            year_elem = pub_date_elem.find("Year")
            month_elem = pub_date_elem.find("Month")
            day_elem = pub_date_elem.find("Day")

            year = year_elem.text if year_elem is not None else None
            month = month_elem.text if month_elem is not None else "01"
            day = day_elem.text if day_elem is not None else "01"

            if year:
                try:
                    # Convert month name to number if needed
                    month_map = {
                        'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                        'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                        'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
                    }
                    month = month_map.get(month, month)

                    pub_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                except Exception as e:
                    logger.warning(f"Could not parse publication date for PMID {pmid}: {e}")

        # Extract DOI
        doi = None
        for article_id in article.findall(".//ArticleId"):
            if article_id.get("IdType") == "doi":
                doi = article_id.text
                break

        # Extract MeSH IDs
        mesh_ids = []
        for mesh_heading in article.findall(".//MeshHeading"):
            descriptor_name = mesh_heading.find(".//DescriptorName")
            if descriptor_name is not None:
                mesh_ui = descriptor_name.get("UI")  # MeSH Unique Identifier (e.g., D008175)
                if mesh_ui:
                    mesh_ids.append(mesh_ui)

        if not title:
            logger.warning(f"No title found for PMID {pmid}")
            return None

        # Truncate title to 200 chars for snippet
        snippet = title[:200] if len(title) > 200 else title

        return {
            "pmid": pmid,
            "title": title,
            "journal": journal,
            "publication_date": pub_date,
            "doi": doi,
            "mesh_ids": mesh_ids,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "snippet": snippet
        }

    except requests.exceptions.Timeout:
        logger.error(f"PubMed API timeout for PMID {pmid}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"PubMed API error for PMID {pmid}: {e}")
        return None
    except ET.ParseError as e:
        logger.error(f"PubMed XML parse error for PMID {pmid}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching PubMed {pmid}: {e}")
        return None


def search_pubmed(query: str, max_results: int = 20) -> List[str]:
    """
    Search PubMed and return list of PMIDs.

    Uses esearch to find articles matching query.

    Args:
        query: PubMed search query (e.g., 'cancer AND TP53')
        max_results: Maximum number of results to return

    Returns:
        List of PMIDs
    """
    try:
        logger.debug(f"Searching PubMed: {query}")

        url = f"{EUTILS_BASE_URL}/esearch.fcgi"
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "xml"
        }

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        # Parse XML response
        root = ET.fromstring(response.content)

        # Extract PMIDs
        pmids = []
        for id_elem in root.findall(".//Id"):
            if id_elem.text:
                pmids.append(id_elem.text)

        logger.debug(f"Found {len(pmids)} PMIDs for query: {query}")
        return pmids

    except Exception as e:
        logger.error(f"PubMed search error: {e}")
        return []


def create_pubmed_evidence(
    cursor: Any,
    pmid: str,
    batch_id: Optional[str] = None,
    created_by: Optional[str] = None
) -> Optional[int]:
    """
    Create evidence record from PubMed article.

    Fetches article metadata and creates evidence row.

    Per Section 24A:
    - source_system = 'pubmed'
    - source_record_id = PMID
    - license = 'NLM_PUBLIC'
    - snippet = title (max 200 chars)

    Args:
        cursor: Database cursor
        pmid: PubMed ID
        batch_id: Optional batch operation ID
        created_by: Optional creator identifier

    Returns:
        evidence_id if created, None on failure
    """
    # Fetch article metadata
    article = fetch_pubmed_article(pmid)

    if not article:
        logger.warning(f"Could not fetch PubMed article {pmid}")
        return None

    # Check if evidence already exists
    cursor.execute("""
        SELECT evidence_id FROM evidence
        WHERE source_system = 'pubmed'
        AND source_record_id = %s
        AND deleted_at IS NULL
    """, (pmid,))

    existing = cursor.fetchone()
    if existing:
        logger.debug(f"Evidence for PMID {pmid} already exists")
        return existing[0]

    # Create evidence record
    cursor.execute("""
        INSERT INTO evidence (
            source_system,
            source_record_id,
            observed_at,
            license,
            uri,
            snippet,
            batch_id,
            created_by
        ) VALUES (
            'pubmed',
            %s,
            %s,
            'NLM_PUBLIC',
            %s,
            %s,
            %s,
            %s
        )
        RETURNING evidence_id
    """, (
        pmid,
        article['publication_date'] or datetime.now().date(),
        article['url'],
        article['snippet'],
        batch_id,
        created_by
    ))

    evidence_id = cursor.fetchone()[0]

    logger.info(f"Created PubMed evidence for PMID {pmid} (evidence_id={evidence_id})")

    # TODO: Store MeSH IDs in separate table or JSON field if needed
    # For now, MeSH IDs are available in article['mesh_ids'] but not persisted

    return evidence_id


def batch_create_pubmed_evidence(
    cursor: Any,
    pmids: List[str],
    batch_id: Optional[str] = None,
    created_by: Optional[str] = None
) -> Dict[str, Optional[int]]:
    """
    Batch create evidence records for multiple PMIDs.

    Args:
        cursor: Database cursor
        pmids: List of PubMed IDs
        batch_id: Optional batch operation ID
        created_by: Optional creator identifier

    Returns:
        Dict mapping pmid → evidence_id (or None if failed)
    """
    results = {}

    for pmid in pmids:
        evidence_id = create_pubmed_evidence(cursor, pmid, batch_id, created_by)
        results[pmid] = evidence_id

    return results


def validate_pmid(pmid: str) -> bool:
    """
    Validate PubMed ID format.

    PMIDs are typically 8-digit integers, but can be shorter or longer.

    Args:
        pmid: PubMed ID to validate

    Returns:
        True if valid PMID format
    """
    return pmid.isdigit() and len(pmid) >= 6 and len(pmid) <= 12
