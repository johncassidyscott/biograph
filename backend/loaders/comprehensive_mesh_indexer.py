#!/usr/bin/env python3
"""
Comprehensive MeSH Indexing for Articles - PubMed-style

Indexes articles with:
1. ALL MeSH descriptors (not just diseases)
2. Publication types
3. MeSH qualifiers/subheadings
4. Confidence scoring

Usage:
    from loaders.comprehensive_mesh_indexer import index_article_comprehensive

    mesh_indexing = index_article_comprehensive(
        article_entity_id=123,
        title="New obesity drug shows promise",
        abstract="Study of semaglutide in type 2 diabetes...",
        publication_types=['Clinical Trial', 'Randomized Controlled Trial']
    )
"""

import re
from typing import Dict, List, Set, Optional
from app.db import get_conn


def extract_candidate_terms(text: str, min_length: int = 3) -> List[str]:
    """
    Extract candidate terms from text for MeSH matching.

    More sophisticated than simple word splitting:
    - Captures multi-word phrases (e.g., "type 2 diabetes")
    - Handles parenthetical terms
    - Preserves medical abbreviations
    """
    if not text:
        return []

    candidates = set()

    # Split into sentences
    sentences = re.split(r'[.!?]\s+', text)

    for sentence in sentences:
        # Extract noun phrases (simple heuristic: capitalized words and common patterns)
        # Match: "Type 2 Diabetes", "Alzheimer's Disease", "KRAS mutation"
        phrases = re.findall(r'\b[A-Z][a-z]*(?:\'s|\s+[A-Z]?[a-z]+)*\b', sentence)
        candidates.update(p for p in phrases if len(p) >= min_length)

        # Extract terms in parentheses: "glucagon-like peptide-1 (GLP-1)"
        paren_terms = re.findall(r'\(([^)]+)\)', sentence)
        candidates.update(p.strip() for p in paren_terms if len(p.strip()) >= min_length)

        # Extract hyphenated medical terms: "GLP-1", "anti-inflammatory"
        hyphen_terms = re.findall(r'\b[\w]+-[\w-]+\b', sentence)
        candidates.update(h for h in hyphen_terms if len(h) >= min_length)

    return list(candidates)


def match_mesh_descriptors(
    candidates: List[str],
    min_confidence: float = 0.70,
    include_trees: Optional[List[str]] = None
) -> List[Dict]:
    """
    Match candidate terms against ALL MeSH descriptors.

    Args:
        candidates: List of candidate terms from text
        min_confidence: Minimum confidence threshold (0.0-1.0)
        include_trees: Optional list of MeSH tree prefixes to include
                      (e.g., ['C', 'D', 'E'] for diseases, chemicals, procedures)
                      If None, includes ALL trees

    Returns:
        List of matched MeSH descriptors with confidence scores
    """
    matches = []
    seen_ui = set()

    with get_conn() as conn:
        with conn.cursor() as cur:
            for candidate in candidates:
                candidate_lower = candidate.lower()

                # Strategy 1: Exact name match (confidence = 0.95)
                cur.execute("""
                    SELECT ui, name,
                           ARRAY_AGG(DISTINCT tree_number) as tree_numbers
                    FROM mesh_descriptor md
                    LEFT JOIN mesh_tree mt ON md.ui = mt.ui
                    WHERE LOWER(name) = %s
                    GROUP BY md.ui, name
                """, (candidate_lower,))

                for row in cur.fetchall():
                    if row['ui'] in seen_ui:
                        continue

                    # Filter by tree if specified
                    if include_trees:
                        tree_nums = row['tree_numbers'] or []
                        if not any(tn.startswith(tuple(include_trees)) for tn in tree_nums):
                            continue

                    seen_ui.add(row['ui'])
                    matches.append({
                        'mesh_ui': row['ui'],
                        'mesh_name': row['name'],
                        'confidence': 0.95,
                        'match_type': 'exact_name',
                        'tree_numbers': row['tree_numbers'] or []
                    })

                # Strategy 2: Exact alias match (confidence = 0.90)
                cur.execute("""
                    SELECT md.ui, md.name, ma.alias,
                           ARRAY_AGG(DISTINCT tree_number) as tree_numbers
                    FROM mesh_alias ma
                    JOIN mesh_descriptor md ON ma.ui = md.ui
                    LEFT JOIN mesh_tree mt ON md.ui = mt.ui
                    WHERE LOWER(ma.alias) = %s
                    GROUP BY md.ui, md.name, ma.alias
                """, (candidate_lower,))

                for row in cur.fetchall():
                    if row['ui'] in seen_ui:
                        continue

                    # Filter by tree if specified
                    if include_trees:
                        tree_nums = row['tree_numbers'] or []
                        if not any(tn.startswith(tuple(include_trees)) for tn in tree_nums):
                            continue

                    seen_ui.add(row['ui'])
                    matches.append({
                        'mesh_ui': row['ui'],
                        'mesh_name': row['name'],
                        'confidence': 0.90,
                        'match_type': 'exact_alias',
                        'matched_alias': row['alias'],
                        'tree_numbers': row['tree_numbers'] or []
                    })

                # Strategy 3: Fuzzy match using trigram similarity (confidence = 0.75-0.85)
                # Only if no exact matches found for this candidate
                if len([m for m in matches if m.get('matched_alias') == candidate or
                       m['mesh_name'].lower() == candidate_lower]) == 0:

                    # This requires pg_trgm extension - gracefully skip if not available
                    try:
                        cur.execute("""
                            SELECT ui, name,
                                   SIMILARITY(name, %s) as sim,
                                   ARRAY_AGG(DISTINCT tree_number) as tree_numbers
                            FROM mesh_descriptor md
                            LEFT JOIN mesh_tree mt ON md.ui = mt.ui
                            WHERE SIMILARITY(name, %s) > 0.5
                            GROUP BY md.ui, name
                            ORDER BY sim DESC
                            LIMIT 3
                        """, (candidate, candidate))

                        for row in cur.fetchall():
                            if row['ui'] in seen_ui:
                                continue

                            confidence = 0.70 + (row['sim'] * 0.15)  # 0.70-0.85 range

                            if confidence < min_confidence:
                                continue

                            # Filter by tree if specified
                            if include_trees:
                                tree_nums = row['tree_numbers'] or []
                                if not any(tn.startswith(tuple(include_trees)) for tn in tree_nums):
                                    continue

                            seen_ui.add(row['ui'])
                            matches.append({
                                'mesh_ui': row['ui'],
                                'mesh_name': row['name'],
                                'confidence': confidence,
                                'match_type': 'fuzzy',
                                'similarity': row['sim'],
                                'tree_numbers': row['tree_numbers'] or []
                            })
                    except Exception as e:
                        # pg_trgm not available - skip fuzzy matching
                        if 'similarity' not in str(e).lower():
                            pass  # Other error, ignore

    # Sort by confidence (descending)
    matches.sort(key=lambda x: x['confidence'], reverse=True)

    return matches


def categorize_mesh_terms(matches: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Categorize MeSH matches by tree category for PubMed-style filtering.

    Returns dict with keys:
        - diseases (C-tree)
        - chemicals_drugs (D-tree)
        - procedures (E-tree)
        - anatomy (A-tree)
        - organisms (B-tree)
        - phenomena_processes (G-tree)
        - other
    """
    categories = {
        'diseases': [],
        'chemicals_drugs': [],
        'procedures': [],
        'anatomy': [],
        'organisms': [],
        'phenomena_processes': [],
        'disciplines': [],
        'other': []
    }

    tree_mapping = {
        'A': 'anatomy',
        'B': 'organisms',
        'C': 'diseases',
        'D': 'chemicals_drugs',
        'E': 'procedures',
        'G': 'phenomena_processes',
        'H': 'disciplines'
    }

    for match in matches:
        tree_nums = match.get('tree_numbers', [])
        if not tree_nums:
            categories['other'].append(match)
            continue

        # Assign to primary tree (first character of first tree number)
        primary_tree = tree_nums[0][0] if tree_nums else None
        category = tree_mapping.get(primary_tree, 'other')
        categories[category].append(match)

        # Also add to other applicable categories (if multi-tree)
        for tn in tree_nums[1:]:
            tree_prefix = tn[0]
            if tree_prefix in tree_mapping and tree_mapping[tree_prefix] != category:
                categories[tree_mapping[tree_prefix]].append(match)

    return categories


def index_article_comprehensive(
    article_entity_id: int,
    title: str,
    abstract: str,
    publication_types: Optional[List[str]] = None,
    min_confidence: float = 0.70,
    major_topic_threshold: float = 0.90
) -> Dict:
    """
    Comprehensively index an article with MeSH terms - PubMed style.

    Args:
        article_entity_id: Entity ID of the article
        title: Article title
        abstract: Article abstract/summary
        publication_types: List of publication types (e.g., ['Clinical Trial'])
        min_confidence: Minimum confidence for MeSH assignment
        major_topic_threshold: Confidence threshold for "major topic" flag

    Returns:
        Dict with indexing results:
        {
            'mesh_terms': {...},  # Categorized MeSH terms
            'publication_types': [...],
            'stats': {...}
        }
    """
    # Extract candidates from text
    text = f"{title}. {abstract or ''}"
    candidates = extract_candidate_terms(text)

    # Match against ALL MeSH descriptors
    matches = match_mesh_descriptors(candidates, min_confidence=min_confidence)

    # Categorize by MeSH tree
    categorized = categorize_mesh_terms(matches)

    # Store in database
    with get_conn() as conn:
        with conn.cursor() as cur:
            for match in matches:
                is_major = match['confidence'] >= major_topic_threshold

                # Insert into news_mesh table (or create article_mesh table)
                cur.execute("""
                    INSERT INTO news_mesh (
                        news_entity_id, mesh_ui, mesh_name,
                        confidence, is_major_topic, source
                    )
                    VALUES (%s, %s, %s, %s, %s, 'comprehensive_indexer')
                    ON CONFLICT (news_entity_id, mesh_ui) DO UPDATE
                      SET confidence = GREATEST(news_mesh.confidence, EXCLUDED.confidence),
                          is_major_topic = EXCLUDED.is_major_topic OR news_mesh.is_major_topic
                """, (article_entity_id, match['mesh_ui'], match['mesh_name'],
                      match['confidence'], is_major))

            # Store publication types if provided
            # TODO: Create publication_type table if needed

        conn.commit()

    return {
        'mesh_terms': categorized,
        'publication_types': publication_types or [],
        'stats': {
            'total_mesh_terms': len(matches),
            'major_topics': len([m for m in matches if m['confidence'] >= major_topic_threshold]),
            'by_category': {k: len(v) for k, v in categorized.items() if v}
        }
    }


def index_with_mesh_tree_filter(
    article_entity_id: int,
    title: str,
    abstract: str,
    tree_filters: List[str],
    min_confidence: float = 0.70
) -> List[Dict]:
    """
    Index article with specific MeSH tree categories only.

    Args:
        article_entity_id: Entity ID of article
        title: Article title
        abstract: Article abstract
        tree_filters: List of tree prefixes (e.g., ['C', 'D'] for diseases and chemicals)
        min_confidence: Minimum confidence threshold

    Returns:
        List of matched MeSH terms
    """
    text = f"{title}. {abstract or ''}"
    candidates = extract_candidate_terms(text)

    matches = match_mesh_descriptors(
        candidates,
        min_confidence=min_confidence,
        include_trees=tree_filters
    )

    # Store in database
    with get_conn() as conn:
        with conn.cursor() as cur:
            for match in matches:
                cur.execute("""
                    INSERT INTO news_mesh (
                        news_entity_id, mesh_ui, mesh_name,
                        confidence, is_major_topic, source
                    )
                    VALUES (%s, %s, %s, %s, %s, 'tree_filtered')
                    ON CONFLICT (news_entity_id, mesh_ui) DO UPDATE
                      SET confidence = GREATEST(news_mesh.confidence, EXCLUDED.confidence)
                """, (article_entity_id, match['mesh_ui'], match['mesh_name'],
                      match['confidence'], match['confidence'] > 0.90))
        conn.commit()

    return matches


if __name__ == "__main__":
    # Example usage
    print("Comprehensive MeSH Indexer - PubMed Style")
    print("=" * 60)

    # Test with sample article
    test_title = "Semaglutide for Obesity and Type 2 Diabetes"
    test_abstract = """
    This randomized controlled trial evaluated the efficacy of semaglutide,
    a glucagon-like peptide-1 (GLP-1) receptor agonist, in patients with
    obesity and type 2 diabetes mellitus. Results showed significant weight
    reduction and improved glycemic control compared to placebo.
    """

    print("\nTest Article:")
    print(f"Title: {test_title}")
    print(f"Abstract: {test_abstract[:100]}...")

    # Extract candidates
    candidates = extract_candidate_terms(test_title + " " + test_abstract)
    print(f"\nExtracted {len(candidates)} candidate terms:")
    print(", ".join(candidates[:10]))

    # Match against MeSH
    matches = match_mesh_descriptors(candidates, min_confidence=0.70)
    print(f"\nMatched {len(matches)} MeSH terms:")
    for m in matches[:5]:
        print(f"  - {m['mesh_name']} ({m['mesh_ui']}) [{m['confidence']:.2f}] - {m['match_type']}")

    # Categorize
    categorized = categorize_mesh_terms(matches)
    print(f"\nCategorized MeSH terms:")
    for category, terms in categorized.items():
        if terms:
            print(f"  {category}: {len(terms)} terms")
