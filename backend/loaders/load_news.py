#!/usr/bin/env python3
"""
News/Press Release Loader with MeSH Indexing

Loads news from RSS feeds and indexes with MeSH terms using entity resolution.
Links news articles to mentioned entities (drugs, diseases, companies, trials).

Supported sources:
- FDA Press Releases
- Fierce Pharma
- Fierce Biotech
- GlobeNewswire (pharma/health)
- BioPharma Dive
- Endpoints News
"""

import re
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional
from dateutil import parser as date_parser

try:
    import feedparser
except ImportError:
    print("⚠️  feedparser not installed. Run: pip install feedparser")
    feedparser = None

from app.db import get_conn
from entity_resolver_v2 import EntityResolverV2


# RSS Feed sources
RSS_SOURCES = [
    {
        "name": "FDA Press Releases",
        "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
        "source_id": "fda_rss",
        "type": "regulatory"
    },
    {
        "name": "Fierce Pharma",
        "url": "https://www.fiercepharma.com/rss/xml",
        "source_id": "fierce_pharma",
        "type": "industry"
    },
    {
        "name": "Fierce Biotech",
        "url": "https://www.fiercebiotech.com/rss/xml",
        "source_id": "fierce_biotech",
        "type": "industry"
    },
    {
        "name": "BioPharma Dive",
        "url": "https://www.biopharmadive.com/feeds/news/",
        "source_id": "biopharma_dive",
        "type": "industry"
    },
    {
        "name": "Endpoints News",
        "url": "https://endpointsnews.com/feed/",
        "source_id": "endpoints_news",
        "type": "industry"
    },
]


def extract_entity_mentions(text: str) -> Set[str]:
    """
    Extract potential entity mentions from text.

    Looks for:
    - Capitalized phrases (2-4 words)
    - Drug-like names
    - Company names
    - Disease terms

    Returns set of candidate entity mentions.
    """
    if not text:
        return set()

    candidates = set()

    # Pattern 1: Capitalized phrases (proper nouns)
    # Match: "Eli Lilly", "Novo Nordisk", "Alzheimer's Disease"
    capitalized_phrases = re.findall(
        r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b',
        text
    )
    candidates.update(capitalized_phrases)

    # Pattern 2: Drug-like suffixes
    drug_patterns = [
        r'\b\w+mab\b',      # Antibodies: pembrolizumab, nivolumab
        r'\b\w+tinib\b',    # Kinase inhibitors: sotorasib
        r'\b\w+tide\b',     # Peptides: semaglutide, tirzepatide
        r'\b\w+ciclib\b',   # CDK inhibitors
    ]
    for pattern in drug_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        candidates.update(matches)

    # Pattern 3: Common disease terms (even if lowercase)
    disease_keywords = [
        'obesity', 'diabetes', 'alzheimer', 'cancer', 'oncology',
        'KRAS', 'lung cancer', 'metabolic', 'cardiovascular'
    ]
    text_lower = text.lower()
    for keyword in disease_keywords:
        if keyword.lower() in text_lower:
            candidates.add(keyword)

    # Filter out common words that aren't entities
    stopwords = {
        'The', 'This', 'That', 'These', 'Those', 'Company', 'Inc',
        'Trial', 'Study', 'Drug', 'Disease', 'Patient', 'Treatment'
    }
    candidates = {c for c in candidates if c not in stopwords}

    return candidates


def index_news_with_mesh(news_entity_id: int, title: str, summary: str) -> Dict:
    """
    Index news article with ALL MeSH terms (not just diseases) - PubMed style.

    Indexes with comprehensive MeSH vocabulary:
    - Diseases (C-tree)
    - Chemicals & Drugs (D-tree)
    - Procedures (E-tree)
    - Anatomy (A-tree)
    - Organisms (B-tree)
    - Phenomena & Processes (G-tree)
    - Disciplines (H-tree)

    Also creates edges to entities in the graph (drugs, diseases, companies).

    Returns dict with:
    - mesh_terms: Dict categorized by type (diseases, chemicals_drugs, procedures, etc.)
    - mentioned_entities: Dict of graph entities mentioned (drug, disease, company)
    """
    from loaders.comprehensive_mesh_indexer import extract_candidate_terms, match_mesh_descriptors, categorize_mesh_terms

    resolver = EntityResolverV2()
    text = f"{title}. {summary or ''}"

    # Extract candidate terms for MeSH matching
    candidates = extract_candidate_terms(text, min_length=3)

    # Match against ALL MeSH descriptors (not just diseases)
    mesh_matches = match_mesh_descriptors(candidates, min_confidence=0.70)

    # Categorize by MeSH tree
    categorized_mesh = categorize_mesh_terms(mesh_matches)

    mentioned_entities = {
        'drugs': [],
        'diseases': [],
        'companies': [],
        'trials': []
    }

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Store all MeSH terms (comprehensive indexing)
            for match in mesh_matches:
                is_major = match['confidence'] >= 0.90

                cur.execute("""
                    INSERT INTO news_mesh (
                        news_entity_id, mesh_ui, mesh_name,
                        confidence, is_major_topic, source
                    )
                    VALUES (%s, %s, %s, %s, %s, 'comprehensive')
                    ON CONFLICT (news_entity_id, mesh_ui) DO UPDATE
                      SET confidence = GREATEST(news_mesh.confidence, EXCLUDED.confidence),
                          is_major_topic = EXCLUDED.is_major_topic OR news_mesh.is_major_topic
                """, (news_entity_id, match['mesh_ui'], match['mesh_name'],
                      match['confidence'], is_major))

            # Also create edges to entities in the graph (for entity-based queries)
            # Extract entity mentions (simpler than candidates)
            entity_candidates = extract_entity_mentions(text)

            for candidate in entity_candidates:
                # Try to resolve as disease entity
                disease = resolver.resolve_disease(candidate)
                if disease.confidence > 0.70:
                    # Create edge: news -> mentions -> disease
                    cur.execute("""
                        INSERT INTO edge (src_id, predicate, dst_id, source, confidence)
                        VALUES (%s, 'mentions', %s, 'news', %s)
                        ON CONFLICT (src_id, predicate, dst_id) DO UPDATE
                          SET confidence = GREATEST(edge.confidence, EXCLUDED.confidence)
                    """, (news_entity_id, disease.entity_id, disease.confidence))
                    mentioned_entities['diseases'].append(disease.name)

                # Try to resolve as drug entity
                drug = resolver.resolve_drug(candidate)
                if drug.confidence > 0.80:
                    cur.execute("""
                        INSERT INTO edge (src_id, predicate, dst_id, source, confidence)
                        VALUES (%s, 'mentions', %s, 'news', %s)
                        ON CONFLICT (src_id, predicate, dst_id) DO UPDATE
                          SET confidence = GREATEST(edge.confidence, EXCLUDED.confidence)
                    """, (news_entity_id, drug.entity_id, drug.confidence))
                    mentioned_entities['drugs'].append(drug.name)

                # Try to resolve as company entity
                company = resolver.resolve_company(candidate)
                if company.confidence > 0.75:
                    cur.execute("""
                        INSERT INTO edge (src_id, predicate, dst_id, source, confidence)
                        VALUES (%s, 'mentions', %s, 'news', %s)
                        ON CONFLICT (src_id, predicate, dst_id) DO UPDATE
                          SET confidence = GREATEST(edge.confidence, EXCLUDED.confidence)
                    """, (news_entity_id, company.entity_id, company.confidence))
                    mentioned_entities['companies'].append(company.name)

        conn.commit()

    return {
        'mesh_terms': categorized_mesh,  # Now categorized by type!
        'mesh_stats': {
            'total': len(mesh_matches),
            'by_category': {k: len(v) for k, v in categorized_mesh.items() if v}
        },
        'mentioned_entities': mentioned_entities
    }


def load_rss_feed(
    source: Dict,
    days_back: int = 30,
    max_items: int = 100
) -> int:
    """
    Load news from a single RSS feed.

    Args:
        source: RSS source config dict
        days_back: Only load articles from last N days
        max_items: Maximum items to process from feed

    Returns:
        Number of new articles loaded
    """
    if feedparser is None:
        print("⚠️  feedparser not installed, skipping RSS feeds")
        return 0

    print(f"\nLoading: {source['name']}")
    print(f"  URL: {source['url']}")

    # Parse RSS feed
    feed = feedparser.parse(source['url'])

    if not feed.entries:
        print("  ⚠️  No entries found in feed")
        return 0

    # Note: EntityResolverV2 doesn't need explicit load_lookup_tables() call
    # It loads on-demand or uses vector search

    cutoff_date = datetime.now() - timedelta(days=days_back)
    inserted = 0
    skipped_old = 0
    skipped_duplicate = 0

    for entry in feed.entries[:max_items]:
        try:
            # Parse published date
            published = None
            if hasattr(entry, 'published'):
                try:
                    published = date_parser.parse(entry.published)
                except:
                    pass

            # Skip old articles
            if published and published < cutoff_date:
                skipped_old += 1
                continue

            # Extract data
            title = entry.get('title', 'Untitled')
            url = entry.get('link', '')
            summary = entry.get('summary', '') or entry.get('description', '')

            if not url:
                continue

            # Create canonical ID from URL hash
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
            canonical_id = f"NEWS:{url_hash}"

            # Check if already exists
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id FROM entity
                        WHERE kind = 'news' AND canonical_id = %s
                    """, (canonical_id,))

                    if cur.fetchone():
                        skipped_duplicate += 1
                        continue

                    # Insert news entity
                    cur.execute("""
                        INSERT INTO entity (kind, canonical_id, name)
                        VALUES ('news', %s, %s)
                        RETURNING id
                    """, (canonical_id, title))
                    news_entity_id = cur.fetchone()['id']

                    # Insert news metadata
                    cur.execute("""
                        INSERT INTO news_item (
                            entity_id, url, published_date, source, summary
                        )
                        VALUES (%s, %s, %s, %s, %s)
                    """, (news_entity_id, url, published, source['source_id'], summary))

                conn.commit()

            # Index with MeSH and link entities
            indexing_result = index_news_with_mesh(news_entity_id, title, summary)

            inserted += 1

            # Print summary
            mesh_count = len(indexing_result['mesh_terms'])
            entity_count = sum(len(v) for v in indexing_result['mentioned_entities'].values())

            if mesh_count > 0 or entity_count > 0:
                print(f"  ✓ {title[:60]}...")
                if mesh_count > 0:
                    print(f"    MeSH: {mesh_count} terms")
                if entity_count > 0:
                    print(f"    Entities: {entity_count} mentions")

        except Exception as e:
            print(f"  ⚠️  Error processing entry: {e}")
            continue

    print(f"\n  Summary:")
    print(f"    New articles: {inserted}")
    print(f"    Skipped (old): {skipped_old}")
    print(f"    Skipped (duplicate): {skipped_duplicate}")

    return inserted


def load_all_news(
    sources: Optional[List[Dict]] = None,
    days_back: int = 30,
    max_items_per_source: int = 100
) -> None:
    """
    Load news from all configured RSS sources.

    Args:
        sources: List of RSS source configs (default: RSS_SOURCES)
        days_back: Only load articles from last N days
        max_items_per_source: Max items to process per feed
    """
    if sources is None:
        sources = RSS_SOURCES

    print("="*60)
    print("LOADING NEWS FROM RSS FEEDS")
    print("="*60)
    print(f"Sources: {len(sources)}")
    print(f"Time window: Last {days_back} days")
    print(f"Max per source: {max_items_per_source} items")

    total_inserted = 0

    for source in sources:
        try:
            count = load_rss_feed(
                source,
                days_back=days_back,
                max_items=max_items_per_source
            )
            total_inserted += count
        except Exception as e:
            print(f"\n⚠️  Error loading {source['name']}: {e}")
            continue

    print("\n" + "="*60)
    print(f"✓ Total news articles loaded: {total_inserted}")

    # Summary statistics
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM entity WHERE kind = 'news'")
            total_news = cur.fetchone()['count']

            cur.execute("SELECT COUNT(*) as count FROM news_mesh")
            total_mesh_tags = cur.fetchone()['count']

            cur.execute("""
                SELECT COUNT(*) as count FROM edge
                WHERE source = 'news' AND predicate = 'mentions'
            """)
            total_mentions = cur.fetchone()['count']

            print(f"✓ Total news in database: {total_news}")
            print(f"✓ Total MeSH tags: {total_mesh_tags}")
            print(f"✓ Total entity mentions: {total_mentions}")

    print("="*60)


if __name__ == "__main__":
    # Load news from last 30 days
    load_all_news(days_back=30, max_items_per_source=50)
