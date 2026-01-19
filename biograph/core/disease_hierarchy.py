"""
BioGraph MVP v8.2 - MeSH Disease Hierarchy

This module provides granular disease categorization based on MeSH tree structure.

Hierarchy Levels:
- Level 1: Therapeutic Area (ONC, CNS, etc.)
- Level 2: Disease Class (Solid Tumors, Neurodegenerative)
- Level 3: Specific Disease (Lung Cancer, Alzheimer's)

MeSH Tree Structure Mapping:
C (Diseases)
├── C04 (Neoplasms) → ONC
│   ├── C04.557 (Neoplasms by Site) → Solid Tumors
│   │   ├── C04.557.470 (Lung Neoplasms) → Lung Cancer
│   │   ├── C04.557.337 (Breast Neoplasms) → Breast Cancer
│   │   └── C04.557.580 (Colorectal Neoplasms) → Colorectal Cancer
│   └── C04.588 (Leukemia/Lymphoma) → Hematologic
├── C10 (Nervous System) → CNS
│   ├── C10.574 (Neurodegenerative) → Neurodegenerative
│   │   ├── C10.574.062 (Alzheimer) → Alzheimer's Disease
│   │   └── C10.574.382 (Parkinson) → Parkinson's Disease
│   └── C10.228 (CNS Diseases)
│       └── C10.228.140.079 (Alzheimer) → Alzheimer's Disease
└── etc.

This is presentation layer ONLY - does NOT affect linkage confidence.
"""

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import re
import logging

logger = logging.getLogger(__name__)


class DiseaseCategory(str, Enum):
    """Disease categories (Level 2)."""
    # Oncology subcategories
    SOLID_TUMORS = "SOLID_TUMORS"
    HEMATOLOGIC_MALIGNANCIES = "HEMATOLOGIC_MALIGNANCIES"

    # CNS subcategories
    NEURODEGENERATIVE = "NEURODEGENERATIVE"
    PSYCHIATRIC = "PSYCHIATRIC"
    MOVEMENT_DISORDERS = "MOVEMENT_DISORDERS"

    # Immunology subcategories
    AUTOIMMUNE = "AUTOIMMUNE"
    INFLAMMATORY = "INFLAMMATORY"

    # CVM subcategories
    CARDIOVASCULAR = "CARDIOVASCULAR"
    METABOLIC = "METABOLIC"

    # ID subcategories
    VIRAL = "VIRAL"
    BACTERIAL = "BACTERIAL"

    # General
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


@dataclass
class DiseaseHierarchy:
    """Hierarchical disease classification."""
    mesh_tree_number: str
    mesh_descriptor_id: Optional[str]
    disease_name: str

    # Hierarchy levels
    therapeutic_area: str  # Level 1 (ONC, CNS, etc.)
    disease_category: str  # Level 2 (SOLID_TUMORS, NEURODEGENERATIVE)
    specific_disease: str  # Level 3 (Lung Cancer, Alzheimer's)

    # Full path for display
    hierarchy_path: List[str] = field(default_factory=list)

    # MeSH tree depth
    tree_depth: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mesh_tree_number": self.mesh_tree_number,
            "mesh_descriptor_id": self.mesh_descriptor_id,
            "disease_name": self.disease_name,
            "therapeutic_area": self.therapeutic_area,
            "disease_category": self.disease_category,
            "specific_disease": self.specific_disease,
            "hierarchy_path": self.hierarchy_path,
            "tree_depth": self.tree_depth
        }


# ============================================================================
# MeSH TREE MAPPINGS
# ============================================================================

# Level 1: Top-level MeSH categories to Therapeutic Areas
MESH_L1_TO_TA = {
    "C01": "ID",      # Bacterial Infections and Mycoses
    "C02": "ID",      # Virus Diseases
    "C03": "ID",      # Parasitic Diseases
    "C04": "ONC",     # Neoplasms
    "C05": "RES",     # Musculoskeletal Diseases (shared with IMM)
    "C06": "CVM",     # Digestive System Diseases
    "C07": "OTHER",   # Stomatognathic Diseases
    "C08": "RES",     # Respiratory Tract Diseases
    "C09": "OTHER",   # Otorhinolaryngologic Diseases
    "C10": "CNS",     # Nervous System Diseases
    "C11": "OTHER",   # Eye Diseases
    "C12": "REN",     # Male Urogenital Diseases
    "C13": "OTHER",   # Female Urogenital Diseases
    "C14": "CVM",     # Cardiovascular Diseases
    "C15": "RARE",    # Hemic and Lymphatic Diseases
    "C16": "RARE",    # Congenital, Hereditary Diseases
    "C17": "IMM",     # Skin and Connective Tissue Diseases
    "C18": "CVM",     # Nutritional and Metabolic Diseases
    "C19": "CVM",     # Endocrine System Diseases
    "C20": "IMM",     # Immune System Diseases
    "C23": "OTHER",   # Pathological Conditions, Signs and Symptoms
    "C25": "OTHER",   # Chemically-Induced Disorders
    "C26": "OTHER",   # Wounds and Injuries
}

# Level 2: Disease categories with specific tree prefixes
MESH_L2_CATEGORIES = {
    # Oncology subcategories
    "C04.557": ("ONC", "SOLID_TUMORS", "Solid Tumors"),  # Neoplasms by Site
    "C04.588": ("ONC", "HEMATOLOGIC_MALIGNANCIES", "Hematologic Malignancies"),  # Neoplasms by Histologic Type
    "C04.697": ("ONC", "HEMATOLOGIC_MALIGNANCIES", "Leukemia"),  # Leukemias

    # CNS subcategories
    "C10.574": ("CNS", "NEURODEGENERATIVE", "Neurodegenerative Diseases"),
    "C10.228": ("CNS", "OTHER", "Central Nervous System Diseases"),
    "C10.597": ("CNS", "PSYCHIATRIC", "Mental Disorders"),
    "C10.720": ("CNS", "MOVEMENT_DISORDERS", "Movement Disorders"),

    # Immunology subcategories
    "C20.111": ("IMM", "AUTOIMMUNE", "Autoimmune Diseases"),
    "C17.300": ("IMM", "INFLAMMATORY", "Inflammatory Skin Diseases"),

    # Cardiovascular subcategories
    "C14.280": ("CVM", "CARDIOVASCULAR", "Heart Diseases"),
    "C14.907": ("CVM", "CARDIOVASCULAR", "Vascular Diseases"),

    # Metabolic subcategories
    "C18.452": ("CVM", "METABOLIC", "Metabolic Diseases"),
    "C19.246": ("CVM", "METABOLIC", "Diabetes Mellitus"),

    # Respiratory
    "C08.127": ("RES", "OTHER", "Bronchial Diseases"),
    "C08.381": ("RES", "OTHER", "Lung Diseases"),

    # Infectious Disease subcategories
    "C01.539": ("ID", "BACTERIAL", "Bacterial Infections"),
    "C02.782": ("ID", "VIRAL", "RNA Virus Infections"),
    "C02.256": ("ID", "VIRAL", "DNA Virus Infections"),
}

# Level 3: Specific diseases with tree numbers
MESH_L3_DISEASES = {
    # Oncology - Solid Tumors
    "C04.557.470": ("ONC", "SOLID_TUMORS", "Lung Cancer"),
    "C04.557.470.200": ("ONC", "SOLID_TUMORS", "Lung Adenocarcinoma"),
    "C04.557.470.700": ("ONC", "SOLID_TUMORS", "Small Cell Lung Cancer"),
    "C04.557.337": ("ONC", "SOLID_TUMORS", "Breast Cancer"),
    "C04.557.337.249": ("ONC", "SOLID_TUMORS", "Triple-Negative Breast Cancer"),
    "C04.557.580": ("ONC", "SOLID_TUMORS", "Colorectal Cancer"),
    "C04.557.580.625": ("ONC", "SOLID_TUMORS", "Rectal Cancer"),
    "C04.557.465": ("ONC", "SOLID_TUMORS", "Liver Cancer"),
    "C04.557.465.625": ("ONC", "SOLID_TUMORS", "Hepatocellular Carcinoma"),
    "C04.557.695": ("ONC", "SOLID_TUMORS", "Pancreatic Cancer"),
    "C04.557.450": ("ONC", "SOLID_TUMORS", "Kidney Cancer"),
    "C04.557.450.795": ("ONC", "SOLID_TUMORS", "Renal Cell Carcinoma"),
    "C04.557.645": ("ONC", "SOLID_TUMORS", "Ovarian Cancer"),
    "C04.557.773": ("ONC", "SOLID_TUMORS", "Prostate Cancer"),
    "C04.557.350": ("ONC", "SOLID_TUMORS", "Head and Neck Cancer"),
    "C04.557.337.600": ("ONC", "SOLID_TUMORS", "HER2-Positive Breast Cancer"),

    # Oncology - Brain Tumors
    "C04.557.470.035": ("ONC", "SOLID_TUMORS", "Brain Metastases"),
    "C04.588.149.828": ("ONC", "SOLID_TUMORS", "Glioblastoma"),

    # Oncology - Hematologic
    "C04.588.364": ("ONC", "HEMATOLOGIC_MALIGNANCIES", "Lymphoma"),
    "C04.588.364.640": ("ONC", "HEMATOLOGIC_MALIGNANCIES", "Non-Hodgkin Lymphoma"),
    "C04.588.364.360": ("ONC", "HEMATOLOGIC_MALIGNANCIES", "Hodgkin Lymphoma"),
    "C04.588.448": ("ONC", "HEMATOLOGIC_MALIGNANCIES", "Multiple Myeloma"),
    "C04.557.227": ("ONC", "HEMATOLOGIC_MALIGNANCIES", "Acute Myeloid Leukemia"),
    "C04.557.291": ("ONC", "HEMATOLOGIC_MALIGNANCIES", "Chronic Lymphocytic Leukemia"),

    # CNS - Neurodegenerative
    "C10.574.062": ("CNS", "NEURODEGENERATIVE", "Alzheimer's Disease"),
    "C10.228.140.079": ("CNS", "NEURODEGENERATIVE", "Alzheimer's Disease"),  # Alternate tree
    "C10.574.382": ("CNS", "NEURODEGENERATIVE", "Huntington Disease"),
    "C10.574.500": ("CNS", "NEURODEGENERATIVE", "Amyotrophic Lateral Sclerosis"),
    "C10.574.812": ("CNS", "NEURODEGENERATIVE", "Parkinson Disease"),
    "C10.720.655": ("CNS", "MOVEMENT_DISORDERS", "Parkinson Disease"),  # Alternate tree
    "C10.574.945": ("CNS", "NEURODEGENERATIVE", "Frontotemporal Dementia"),
    "C10.574.281": ("CNS", "NEURODEGENERATIVE", "Dementia"),

    # CNS - Psychiatric
    "C10.597.350": ("CNS", "PSYCHIATRIC", "Depression"),
    "C10.597.350.400": ("CNS", "PSYCHIATRIC", "Major Depressive Disorder"),
    "C10.597.350.150": ("CNS", "PSYCHIATRIC", "Bipolar Disorder"),
    "C10.597.751": ("CNS", "PSYCHIATRIC", "Schizophrenia"),
    "C10.597.606": ("CNS", "PSYCHIATRIC", "Anxiety Disorders"),
    "C10.597.606.643": ("CNS", "PSYCHIATRIC", "PTSD"),

    # Immunology - Autoimmune
    "C20.111.198": ("IMM", "AUTOIMMUNE", "Rheumatoid Arthritis"),
    "C20.111.590": ("IMM", "AUTOIMMUNE", "Multiple Sclerosis"),
    "C20.111.730": ("IMM", "AUTOIMMUNE", "Lupus"),
    "C20.111.430": ("IMM", "AUTOIMMUNE", "Inflammatory Bowel Disease"),
    "C20.111.430.500": ("IMM", "AUTOIMMUNE", "Crohn's Disease"),
    "C20.111.430.500.600": ("IMM", "AUTOIMMUNE", "Ulcerative Colitis"),
    "C20.111.682": ("IMM", "AUTOIMMUNE", "Psoriasis"),

    # Cardiovascular
    "C14.280.238": ("CVM", "CARDIOVASCULAR", "Cardiomyopathy"),
    "C14.280.434": ("CVM", "CARDIOVASCULAR", "Heart Failure"),
    "C14.280.647": ("CVM", "CARDIOVASCULAR", "Myocardial Infarction"),
    "C14.280.067": ("CVM", "CARDIOVASCULAR", "Arrhythmias"),
    "C14.907.137": ("CVM", "CARDIOVASCULAR", "Atherosclerosis"),
    "C14.907.489": ("CVM", "CARDIOVASCULAR", "Hypertension"),

    # Metabolic
    "C18.452.394.750": ("CVM", "METABOLIC", "Type 2 Diabetes"),
    "C18.452.394.750.149": ("CVM", "METABOLIC", "Type 1 Diabetes"),
    "C18.452.625": ("CVM", "METABOLIC", "Obesity"),
    "C18.452.584": ("CVM", "METABOLIC", "NAFLD"),
    "C18.452.584.625": ("CVM", "METABOLIC", "NASH"),
    "C18.452.394.952": ("CVM", "METABOLIC", "Metabolic Syndrome"),

    # Respiratory
    "C08.127.108": ("RES", "OTHER", "Asthma"),
    "C08.381.495.389": ("RES", "OTHER", "COPD"),
    "C08.381.520": ("RES", "OTHER", "Pulmonary Fibrosis"),
    "C08.381.472": ("RES", "OTHER", "Cystic Fibrosis"),

    # Infectious Disease
    "C02.782.815.616": ("ID", "VIRAL", "HIV/AIDS"),
    "C02.256.466": ("ID", "VIRAL", "Hepatitis B"),
    "C02.440.440": ("ID", "VIRAL", "Hepatitis C"),
    "C02.782.600.550": ("ID", "VIRAL", "COVID-19"),
    "C02.782.580": ("ID", "VIRAL", "Influenza"),
    "C02.782.815.200": ("ID", "VIRAL", "RSV Infection"),
    "C01.539.463": ("ID", "BACTERIAL", "Tuberculosis"),

    # Renal
    "C12.777.419": ("REN", "OTHER", "Chronic Kidney Disease"),
    "C12.777.419.155": ("REN", "OTHER", "Diabetic Nephropathy"),
    "C12.777.419.570": ("REN", "OTHER", "Glomerulonephritis"),

    # Rare Diseases
    "C16.320.565": ("RARE", "OTHER", "Cystic Fibrosis"),
    "C16.320.322": ("RARE", "OTHER", "Duchenne Muscular Dystrophy"),
    "C16.320.400": ("RARE", "OTHER", "Hemophilia"),
    "C16.320.840": ("RARE", "OTHER", "Sickle Cell Disease"),
}


def get_mesh_hierarchy(mesh_tree_number: str) -> DiseaseHierarchy:
    """
    Get disease hierarchy for a MeSH tree number.

    Args:
        mesh_tree_number: MeSH tree number (e.g., 'C04.557.470')

    Returns:
        DiseaseHierarchy with all classification levels
    """
    # Validate format
    if not re.match(r'^[A-Z]\d{2}(\.\d{3})*$', mesh_tree_number):
        logger.warning(f"Invalid MeSH tree number format: {mesh_tree_number}")
        return DiseaseHierarchy(
            mesh_tree_number=mesh_tree_number,
            mesh_descriptor_id=None,
            disease_name=mesh_tree_number,
            therapeutic_area="UNKNOWN",
            disease_category="UNKNOWN",
            specific_disease=mesh_tree_number,
            hierarchy_path=[mesh_tree_number],
            tree_depth=0
        )

    # Calculate tree depth
    parts = mesh_tree_number.split('.')
    tree_depth = len(parts)

    # Extract L1 category
    l1_prefix = mesh_tree_number[:3]  # e.g., "C04"
    therapeutic_area = MESH_L1_TO_TA.get(l1_prefix, "UNKNOWN")

    # Build hierarchy path
    hierarchy_path = []

    # Check for specific disease match (L3) first
    specific_disease = mesh_tree_number
    disease_category = "OTHER"
    disease_name = mesh_tree_number

    # Try exact match in L3
    if mesh_tree_number in MESH_L3_DISEASES:
        ta, cat, name = MESH_L3_DISEASES[mesh_tree_number]
        therapeutic_area = ta
        disease_category = cat
        specific_disease = name
        disease_name = name
    else:
        # Try progressively shorter prefixes for L3
        current = mesh_tree_number
        while '.' in current:
            if current in MESH_L3_DISEASES:
                ta, cat, name = MESH_L3_DISEASES[current]
                therapeutic_area = ta
                disease_category = cat
                specific_disease = name
                break
            current = current.rsplit('.', 1)[0]

        # If no L3 match, try L2
        current = mesh_tree_number
        while '.' in current:
            if current in MESH_L2_CATEGORIES:
                ta, cat, name = MESH_L2_CATEGORIES[current]
                therapeutic_area = ta
                disease_category = cat
                disease_name = name
                break
            current = current.rsplit('.', 1)[0]

    # Build hierarchy path
    if therapeutic_area != "UNKNOWN":
        hierarchy_path.append(get_ta_display_name(therapeutic_area))
    if disease_category != "OTHER" and disease_category != "UNKNOWN":
        hierarchy_path.append(get_category_display_name(disease_category))
    hierarchy_path.append(specific_disease)

    return DiseaseHierarchy(
        mesh_tree_number=mesh_tree_number,
        mesh_descriptor_id=None,
        disease_name=disease_name,
        therapeutic_area=therapeutic_area,
        disease_category=disease_category,
        specific_disease=specific_disease,
        hierarchy_path=hierarchy_path,
        tree_depth=tree_depth
    )


def get_ta_display_name(ta_code: str) -> str:
    """Get display name for therapeutic area code."""
    display_names = {
        "ONC": "Oncology",
        "CNS": "Central Nervous System",
        "IMM": "Immunology",
        "CVM": "Cardiovascular & Metabolic",
        "ID": "Infectious Disease",
        "RARE": "Rare Disease",
        "RES": "Respiratory",
        "REN": "Renal",
        "OTHER": "Other",
        "UNKNOWN": "Unknown"
    }
    return display_names.get(ta_code, ta_code)


def get_category_display_name(category: str) -> str:
    """Get display name for disease category."""
    display_names = {
        "SOLID_TUMORS": "Solid Tumors",
        "HEMATOLOGIC_MALIGNANCIES": "Hematologic Malignancies",
        "NEURODEGENERATIVE": "Neurodegenerative Diseases",
        "PSYCHIATRIC": "Psychiatric Disorders",
        "MOVEMENT_DISORDERS": "Movement Disorders",
        "AUTOIMMUNE": "Autoimmune Diseases",
        "INFLAMMATORY": "Inflammatory Diseases",
        "CARDIOVASCULAR": "Cardiovascular Diseases",
        "METABOLIC": "Metabolic Diseases",
        "VIRAL": "Viral Infections",
        "BACTERIAL": "Bacterial Infections",
        "OTHER": "Other",
        "UNKNOWN": "Unknown"
    }
    return display_names.get(category, category)


def get_diseases_by_category(category: str) -> List[Tuple[str, str]]:
    """
    Get all diseases in a category.

    Args:
        category: Disease category (e.g., 'SOLID_TUMORS')

    Returns:
        List of (tree_number, disease_name) tuples
    """
    results = []
    for tree_number, (ta, cat, name) in MESH_L3_DISEASES.items():
        if cat == category:
            results.append((tree_number, name))
    return sorted(results, key=lambda x: x[1])


def get_diseases_by_ta(therapeutic_area: str) -> List[Tuple[str, str, str]]:
    """
    Get all diseases in a therapeutic area.

    Args:
        therapeutic_area: TA code (e.g., 'ONC')

    Returns:
        List of (tree_number, category, disease_name) tuples
    """
    results = []
    for tree_number, (ta, cat, name) in MESH_L3_DISEASES.items():
        if ta == therapeutic_area:
            results.append((tree_number, cat, name))
    return sorted(results, key=lambda x: (x[1], x[2]))


def get_hierarchy_path(mesh_tree_number: str) -> str:
    """
    Get human-readable hierarchy path.

    Args:
        mesh_tree_number: MeSH tree number

    Returns:
        String like "Oncology > Solid Tumors > Lung Cancer"
    """
    hierarchy = get_mesh_hierarchy(mesh_tree_number)
    return " > ".join(hierarchy.hierarchy_path)


def search_diseases(query: str, limit: int = 20) -> List[DiseaseHierarchy]:
    """
    Search for diseases by name.

    Args:
        query: Search query
        limit: Maximum results

    Returns:
        List of matching DiseaseHierarchy objects
    """
    query_lower = query.lower()
    results = []

    for tree_number, (ta, cat, name) in MESH_L3_DISEASES.items():
        if query_lower in name.lower():
            results.append(get_mesh_hierarchy(tree_number))

    # Sort by relevance (exact match first, then alphabetical)
    results.sort(key=lambda h: (
        0 if h.specific_disease.lower() == query_lower else 1,
        h.specific_disease
    ))

    return results[:limit]


# ============================================================================
# DATABASE INTEGRATION
# ============================================================================

def populate_hierarchy_mappings(cursor: Any) -> Dict[str, int]:
    """
    Populate therapeutic_area_mapping table with full MeSH hierarchy.

    Args:
        cursor: Database cursor

    Returns:
        Dict with counts of mappings created per TA
    """
    stats = {}

    # Insert L2 category mappings
    for tree_prefix, (ta, category, name) in MESH_L2_CATEGORIES.items():
        try:
            cursor.execute("""
                INSERT INTO therapeutic_area_mapping (
                    ta_code, ontology_type, ontology_value, priority, notes
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ontology_type, ontology_value) DO NOTHING
            """, (ta, 'mesh_tree', f'{tree_prefix}%', 50, f'L2: {name}'))
            stats[ta] = stats.get(ta, 0) + 1
        except Exception as e:
            logger.warning(f"Error inserting L2 mapping {tree_prefix}: {e}")

    # Insert L3 specific disease mappings
    for tree_number, (ta, category, name) in MESH_L3_DISEASES.items():
        try:
            cursor.execute("""
                INSERT INTO therapeutic_area_mapping (
                    ta_code, ontology_type, ontology_value, priority, notes
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ontology_type, ontology_value) DO NOTHING
            """, (ta, 'mesh_tree', f'{tree_number}%', 100, f'L3: {name}'))
            stats[ta] = stats.get(ta, 0) + 1
        except Exception as e:
            logger.warning(f"Error inserting L3 mapping {tree_number}: {e}")

    logger.info(f"Populated hierarchy mappings: {stats}")
    return stats


def get_disease_hierarchy_from_db(
    cursor: Any,
    mesh_tree_number: str
) -> Optional[DiseaseHierarchy]:
    """
    Get disease hierarchy using database lookups.

    Args:
        cursor: Database cursor
        mesh_tree_number: MeSH tree number

    Returns:
        DiseaseHierarchy from database or None
    """
    # First use in-memory mappings for classification
    hierarchy = get_mesh_hierarchy(mesh_tree_number)

    # Then enrich with database TA if available
    try:
        cursor.execute("""
            SELECT ta_code, notes
            FROM therapeutic_area_mapping
            WHERE ontology_type = 'mesh_tree'
            AND %s LIKE REPLACE(ontology_value, '%%', '')
            ORDER BY priority DESC
            LIMIT 1
        """, (mesh_tree_number,))

        row = cursor.fetchone()
        if row:
            hierarchy.therapeutic_area = row[0]
    except Exception as e:
        logger.warning(f"Error getting hierarchy from DB for {mesh_tree_number}: {e}")

    return hierarchy
