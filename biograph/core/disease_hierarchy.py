"""
BioGraph MVP v8.3 - Therapeutic Area Disease Taxonomy

This module provides a business-aligned disease categorization using MeSH Descriptor UIDs.

Hierarchy Levels:
- Level 1: Therapeutic Area (Oncology, Neuroscience, etc.)
- Level 2: Segment (Solid Tumors, Neurology, etc.)
- Level 3: Market Driver Anchor (specific diseases with MeSH Descriptor UIDs)

Key Design Decisions:
1. Uses MeSH Descriptor UIDs (D######) NOT tree numbers
2. Single canonical location per disease (no polyhierarchy)
3. Business/market aligned naming conventions
4. Presentation layer ONLY - does NOT affect linkage confidence

MeSH Descriptor UIDs are stable identifiers that don't change when
the MeSH tree structure is reorganized.
"""

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# LEVEL 1: THERAPEUTIC AREAS
# ============================================================================

class TherapeuticArea(str, Enum):
    """Level 1 - Therapeutic Areas (business-aligned)."""
    ONCOLOGY = "Oncology"
    IMMUNOLOGY_INFLAMMATION = "Immunology & Inflammation"
    CARDIOMETABOLIC_RENAL = "Cardiometabolic & Renal"
    NEUROSCIENCE = "Neuroscience"
    INFECTIOUS_DISEASES = "Infectious Diseases"
    RARE_GENETIC = "Rare & Genetic Medicine"
    OPHTHALMOLOGY = "Ophthalmology"
    SPECIALTY_OTHER = "Specialty & Other"


# ============================================================================
# LEVEL 2: SEGMENTS
# ============================================================================

class Segment(str, Enum):
    """Level 2 - Segments within Therapeutic Areas."""
    # Oncology segments
    SOLID_TUMORS = "Solid Tumors"
    HEMATOLOGIC_MALIGNANCIES = "Hematologic Malignancies"

    # Immunology & Inflammation segments
    RHEUMATOLOGY = "Rheumatology"
    BARRIER_INFLAMMATION = "Barrier Inflammation"

    # Cardiometabolic & Renal segments
    METABOLIC_OBESITY = "Metabolic & Obesity"
    CV_RENAL = "CV & Renal"

    # Neuroscience segments
    NEUROLOGY = "Neurology"
    PSYCHIATRY = "Psychiatry"

    # Infectious Diseases segments
    VIRAL_VACCINES = "Viral & Vaccines"
    BACTERIAL_FUNGAL = "Bacterial & Fungal"

    # Rare & Genetic segments
    MONOGENIC_RARE = "Monogenic Rare"

    # Ophthalmology segments
    RETINAL_DISEASE = "Retinal Disease"

    # Specialty & Other segments
    WOMENS_HEALTH = "Women's Health"
    RESPIRATORY = "Respiratory"
    OTHER = "Other"


# ============================================================================
# SEGMENT TO THERAPEUTIC AREA MAPPING
# ============================================================================

SEGMENT_TO_TA: Dict[Segment, TherapeuticArea] = {
    # Oncology
    Segment.SOLID_TUMORS: TherapeuticArea.ONCOLOGY,
    Segment.HEMATOLOGIC_MALIGNANCIES: TherapeuticArea.ONCOLOGY,

    # Immunology & Inflammation
    Segment.RHEUMATOLOGY: TherapeuticArea.IMMUNOLOGY_INFLAMMATION,
    Segment.BARRIER_INFLAMMATION: TherapeuticArea.IMMUNOLOGY_INFLAMMATION,

    # Cardiometabolic & Renal
    Segment.METABOLIC_OBESITY: TherapeuticArea.CARDIOMETABOLIC_RENAL,
    Segment.CV_RENAL: TherapeuticArea.CARDIOMETABOLIC_RENAL,

    # Neuroscience
    Segment.NEUROLOGY: TherapeuticArea.NEUROSCIENCE,
    Segment.PSYCHIATRY: TherapeuticArea.NEUROSCIENCE,

    # Infectious Diseases
    Segment.VIRAL_VACCINES: TherapeuticArea.INFECTIOUS_DISEASES,
    Segment.BACTERIAL_FUNGAL: TherapeuticArea.INFECTIOUS_DISEASES,

    # Rare & Genetic
    Segment.MONOGENIC_RARE: TherapeuticArea.RARE_GENETIC,

    # Ophthalmology
    Segment.RETINAL_DISEASE: TherapeuticArea.OPHTHALMOLOGY,

    # Specialty & Other
    Segment.WOMENS_HEALTH: TherapeuticArea.SPECIALTY_OTHER,
    Segment.RESPIRATORY: TherapeuticArea.SPECIALTY_OTHER,
    Segment.OTHER: TherapeuticArea.SPECIALTY_OTHER,
}


# ============================================================================
# LEVEL 3: DISEASE TAXONOMY (MeSH Descriptor UID based)
# ============================================================================

@dataclass
class DiseaseEntry:
    """A disease in the taxonomy with its MeSH Descriptor UID."""
    mesh_descriptor_uid: str  # D###### format
    name: str                 # Display name (Market Driver Anchor)
    segment: Segment          # L2 classification
    synonyms: List[str] = field(default_factory=list)

    @property
    def therapeutic_area(self) -> TherapeuticArea:
        """Get L1 therapeutic area from segment."""
        return SEGMENT_TO_TA[self.segment]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mesh_descriptor_uid": self.mesh_descriptor_uid,
            "name": self.name,
            "segment": self.segment.value,
            "therapeutic_area": self.therapeutic_area.value,
            "synonyms": self.synonyms,
        }


# ============================================================================
# DISEASE TAXONOMY DATABASE
# Single canonical location per disease - no polyhierarchy
# ============================================================================

DISEASE_TAXONOMY: Dict[str, DiseaseEntry] = {
    # ==========================================================================
    # ONCOLOGY - SOLID TUMORS
    # ==========================================================================
    "D008175": DiseaseEntry(
        mesh_descriptor_uid="D008175",
        name="Lung Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Lung Neoplasms", "Pulmonary Cancer"],
    ),
    "D002289": DiseaseEntry(
        mesh_descriptor_uid="D002289",
        name="NSCLC",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Non-Small Cell Lung Cancer", "Carcinoma, Non-Small-Cell Lung"],
    ),
    "D055752": DiseaseEntry(
        mesh_descriptor_uid="D055752",
        name="Small Cell Lung Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["SCLC", "Carcinoma, Small Cell Lung"],
    ),
    "D001943": DiseaseEntry(
        mesh_descriptor_uid="D001943",
        name="Breast Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Breast Neoplasms", "Mammary Cancer"],
    ),
    "D064726": DiseaseEntry(
        mesh_descriptor_uid="D064726",
        name="Triple-Negative Breast Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["TNBC"],
    ),
    "D015179": DiseaseEntry(
        mesh_descriptor_uid="D015179",
        name="Colorectal Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Colorectal Neoplasms", "CRC"],
    ),
    "D010190": DiseaseEntry(
        mesh_descriptor_uid="D010190",
        name="Pancreatic Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Pancreatic Neoplasms", "Pancreatic Ductal Adenocarcinoma", "PDAC"],
    ),
    "D011471": DiseaseEntry(
        mesh_descriptor_uid="D011471",
        name="Prostate Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Prostatic Neoplasms"],
    ),
    "D010051": DiseaseEntry(
        mesh_descriptor_uid="D010051",
        name="Ovarian Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Ovarian Neoplasms"],
    ),
    "D006528": DiseaseEntry(
        mesh_descriptor_uid="D006528",
        name="Hepatocellular Carcinoma",
        segment=Segment.SOLID_TUMORS,
        synonyms=["HCC", "Liver Cancer", "Carcinoma, Hepatocellular"],
    ),
    "D002292": DiseaseEntry(
        mesh_descriptor_uid="D002292",
        name="Renal Cell Carcinoma",
        segment=Segment.SOLID_TUMORS,
        synonyms=["RCC", "Kidney Cancer", "Carcinoma, Renal Cell"],
    ),
    "D008545": DiseaseEntry(
        mesh_descriptor_uid="D008545",
        name="Melanoma",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Malignant Melanoma"],
    ),
    "D005909": DiseaseEntry(
        mesh_descriptor_uid="D005909",
        name="Glioblastoma",
        segment=Segment.SOLID_TUMORS,
        synonyms=["GBM", "Glioblastoma Multiforme"],
    ),
    "D006258": DiseaseEntry(
        mesh_descriptor_uid="D006258",
        name="Head and Neck Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Head and Neck Neoplasms", "HNSCC"],
    ),
    "D001661": DiseaseEntry(
        mesh_descriptor_uid="D001661",
        name="Bladder Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Urinary Bladder Neoplasms"],
    ),
    "D013274": DiseaseEntry(
        mesh_descriptor_uid="D013274",
        name="Gastric Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Stomach Neoplasms", "Stomach Cancer"],
    ),
    "D004938": DiseaseEntry(
        mesh_descriptor_uid="D004938",
        name="Esophageal Cancer",
        segment=Segment.SOLID_TUMORS,
        synonyms=["Esophageal Neoplasms"],
    ),

    # ==========================================================================
    # ONCOLOGY - HEMATOLOGIC MALIGNANCIES
    # ==========================================================================
    "D009101": DiseaseEntry(
        mesh_descriptor_uid="D009101",
        name="Multiple Myeloma",
        segment=Segment.HEMATOLOGIC_MALIGNANCIES,
        synonyms=["MM", "Plasma Cell Myeloma"],
    ),
    "D008228": DiseaseEntry(
        mesh_descriptor_uid="D008228",
        name="Lymphoma",
        segment=Segment.HEMATOLOGIC_MALIGNANCIES,
        synonyms=["Lymphomas"],
    ),
    "D008223": DiseaseEntry(
        mesh_descriptor_uid="D008223",
        name="Non-Hodgkin Lymphoma",
        segment=Segment.HEMATOLOGIC_MALIGNANCIES,
        synonyms=["NHL", "Lymphoma, Non-Hodgkin"],
    ),
    "D006689": DiseaseEntry(
        mesh_descriptor_uid="D006689",
        name="Hodgkin Lymphoma",
        segment=Segment.HEMATOLOGIC_MALIGNANCIES,
        synonyms=["Hodgkin Disease"],
    ),
    "D016403": DiseaseEntry(
        mesh_descriptor_uid="D016403",
        name="Diffuse Large B-Cell Lymphoma",
        segment=Segment.HEMATOLOGIC_MALIGNANCIES,
        synonyms=["DLBCL"],
    ),
    "D015464": DiseaseEntry(
        mesh_descriptor_uid="D015464",
        name="Acute Myeloid Leukemia",
        segment=Segment.HEMATOLOGIC_MALIGNANCIES,
        synonyms=["AML", "Leukemia, Myeloid, Acute"],
    ),
    "D015451": DiseaseEntry(
        mesh_descriptor_uid="D015451",
        name="Chronic Lymphocytic Leukemia",
        segment=Segment.HEMATOLOGIC_MALIGNANCIES,
        synonyms=["CLL", "Leukemia, Lymphocytic, Chronic, B-Cell"],
    ),
    "D015470": DiseaseEntry(
        mesh_descriptor_uid="D015470",
        name="Chronic Myeloid Leukemia",
        segment=Segment.HEMATOLOGIC_MALIGNANCIES,
        synonyms=["CML", "Leukemia, Myelogenous, Chronic, BCR-ABL Positive"],
    ),
    "D054198": DiseaseEntry(
        mesh_descriptor_uid="D054198",
        name="Acute Lymphoblastic Leukemia",
        segment=Segment.HEMATOLOGIC_MALIGNANCIES,
        synonyms=["ALL", "Precursor Cell Lymphoblastic Leukemia-Lymphoma"],
    ),
    "D009190": DiseaseEntry(
        mesh_descriptor_uid="D009190",
        name="Myelodysplastic Syndromes",
        segment=Segment.HEMATOLOGIC_MALIGNANCIES,
        synonyms=["MDS"],
    ),

    # ==========================================================================
    # IMMUNOLOGY & INFLAMMATION - RHEUMATOLOGY
    # ==========================================================================
    "D001172": DiseaseEntry(
        mesh_descriptor_uid="D001172",
        name="Rheumatoid Arthritis",
        segment=Segment.RHEUMATOLOGY,
        synonyms=["RA", "Arthritis, Rheumatoid"],
    ),
    "D008180": DiseaseEntry(
        mesh_descriptor_uid="D008180",
        name="Systemic Lupus Erythematosus",
        segment=Segment.RHEUMATOLOGY,
        synonyms=["SLE", "Lupus"],
    ),
    "D013167": DiseaseEntry(
        mesh_descriptor_uid="D013167",
        name="Ankylosing Spondylitis",
        segment=Segment.RHEUMATOLOGY,
        synonyms=["Spondylitis, Ankylosing", "AS"],
    ),
    "D015535": DiseaseEntry(
        mesh_descriptor_uid="D015535",
        name="Psoriatic Arthritis",
        segment=Segment.RHEUMATOLOGY,
        synonyms=["Arthritis, Psoriatic", "PsA"],
    ),
    "D012859": DiseaseEntry(
        mesh_descriptor_uid="D012859",
        name="Sjogren Syndrome",
        segment=Segment.RHEUMATOLOGY,
        synonyms=["Sjogren's Syndrome"],
    ),
    "D013586": DiseaseEntry(
        mesh_descriptor_uid="D013586",
        name="Systemic Sclerosis",
        segment=Segment.RHEUMATOLOGY,
        synonyms=["Scleroderma, Systemic", "SSc"],
    ),

    # ==========================================================================
    # IMMUNOLOGY & INFLAMMATION - BARRIER INFLAMMATION
    # ==========================================================================
    "D011565": DiseaseEntry(
        mesh_descriptor_uid="D011565",
        name="Psoriasis",
        segment=Segment.BARRIER_INFLAMMATION,
        synonyms=[],
    ),
    "D003424": DiseaseEntry(
        mesh_descriptor_uid="D003424",
        name="Crohn Disease",
        segment=Segment.BARRIER_INFLAMMATION,
        synonyms=["Crohn's Disease", "Regional Enteritis"],
    ),
    "D003093": DiseaseEntry(
        mesh_descriptor_uid="D003093",
        name="Ulcerative Colitis",
        segment=Segment.BARRIER_INFLAMMATION,
        synonyms=["Colitis, Ulcerative", "UC"],
    ),
    "D015212": DiseaseEntry(
        mesh_descriptor_uid="D015212",
        name="Inflammatory Bowel Disease",
        segment=Segment.BARRIER_INFLAMMATION,
        synonyms=["IBD", "Inflammatory Bowel Diseases"],
    ),
    "D003876": DiseaseEntry(
        mesh_descriptor_uid="D003876",
        name="Atopic Dermatitis",
        segment=Segment.BARRIER_INFLAMMATION,
        synonyms=["Dermatitis, Atopic", "Eczema"],
    ),
    "D000080909": DiseaseEntry(
        mesh_descriptor_uid="D000080909",
        name="Hidradenitis Suppurativa",
        segment=Segment.BARRIER_INFLAMMATION,
        synonyms=["HS"],
    ),

    # ==========================================================================
    # CARDIOMETABOLIC & RENAL - METABOLIC & OBESITY
    # ==========================================================================
    "D003924": DiseaseEntry(
        mesh_descriptor_uid="D003924",
        name="Type 2 Diabetes",
        segment=Segment.METABOLIC_OBESITY,
        synonyms=["T2D", "Diabetes Mellitus, Type 2", "Type 2 Diabetes Mellitus"],
    ),
    "D003922": DiseaseEntry(
        mesh_descriptor_uid="D003922",
        name="Type 1 Diabetes",
        segment=Segment.METABOLIC_OBESITY,
        synonyms=["T1D", "Diabetes Mellitus, Type 1", "Type 1 Diabetes Mellitus"],
    ),
    "D009765": DiseaseEntry(
        mesh_descriptor_uid="D009765",
        name="Obesity",
        segment=Segment.METABOLIC_OBESITY,
        synonyms=[],
    ),
    "D065626": DiseaseEntry(
        mesh_descriptor_uid="D065626",
        name="NAFLD",
        segment=Segment.METABOLIC_OBESITY,
        synonyms=["Non-alcoholic Fatty Liver Disease", "Fatty Liver Disease"],
    ),
    "D000071683": DiseaseEntry(
        mesh_descriptor_uid="D000071683",
        name="NASH",
        segment=Segment.METABOLIC_OBESITY,
        synonyms=["Non-alcoholic Steatohepatitis", "MASH", "Metabolic Steatohepatitis"],
    ),
    "D024821": DiseaseEntry(
        mesh_descriptor_uid="D024821",
        name="Metabolic Syndrome",
        segment=Segment.METABOLIC_OBESITY,
        synonyms=["Metabolic Syndrome X"],
    ),

    # ==========================================================================
    # CARDIOMETABOLIC & RENAL - CV & RENAL
    # ==========================================================================
    "D006333": DiseaseEntry(
        mesh_descriptor_uid="D006333",
        name="Heart Failure",
        segment=Segment.CV_RENAL,
        synonyms=["Cardiac Failure", "Congestive Heart Failure", "CHF"],
    ),
    "D006973": DiseaseEntry(
        mesh_descriptor_uid="D006973",
        name="Hypertension",
        segment=Segment.CV_RENAL,
        synonyms=["High Blood Pressure"],
    ),
    "D050197": DiseaseEntry(
        mesh_descriptor_uid="D050197",
        name="Atherosclerosis",
        segment=Segment.CV_RENAL,
        synonyms=[],
    ),
    "D009203": DiseaseEntry(
        mesh_descriptor_uid="D009203",
        name="Myocardial Infarction",
        segment=Segment.CV_RENAL,
        synonyms=["MI", "Heart Attack"],
    ),
    "D001281": DiseaseEntry(
        mesh_descriptor_uid="D001281",
        name="Atrial Fibrillation",
        segment=Segment.CV_RENAL,
        synonyms=["AFib", "AF"],
    ),
    "D051436": DiseaseEntry(
        mesh_descriptor_uid="D051436",
        name="Chronic Kidney Disease",
        segment=Segment.CV_RENAL,
        synonyms=["CKD", "Renal Insufficiency, Chronic"],
    ),
    "D003928": DiseaseEntry(
        mesh_descriptor_uid="D003928",
        name="Diabetic Nephropathy",
        segment=Segment.CV_RENAL,
        synonyms=["Diabetic Kidney Disease", "DKD"],
    ),

    # ==========================================================================
    # NEUROSCIENCE - NEUROLOGY
    # ==========================================================================
    "D000544": DiseaseEntry(
        mesh_descriptor_uid="D000544",
        name="Alzheimer Disease",
        segment=Segment.NEUROLOGY,
        synonyms=["Alzheimer's Disease", "AD"],
    ),
    "D010300": DiseaseEntry(
        mesh_descriptor_uid="D010300",
        name="Parkinson Disease",
        segment=Segment.NEUROLOGY,
        synonyms=["Parkinson's Disease", "PD"],
    ),
    "D009103": DiseaseEntry(
        mesh_descriptor_uid="D009103",
        name="Multiple Sclerosis",
        segment=Segment.NEUROLOGY,
        synonyms=["MS"],
    ),
    "D000690": DiseaseEntry(
        mesh_descriptor_uid="D000690",
        name="Amyotrophic Lateral Sclerosis",
        segment=Segment.NEUROLOGY,
        synonyms=["ALS", "Lou Gehrig Disease"],
    ),
    "D006816": DiseaseEntry(
        mesh_descriptor_uid="D006816",
        name="Huntington Disease",
        segment=Segment.NEUROLOGY,
        synonyms=["Huntington's Disease", "HD"],
    ),
    "D004827": DiseaseEntry(
        mesh_descriptor_uid="D004827",
        name="Epilepsy",
        segment=Segment.NEUROLOGY,
        synonyms=["Seizure Disorder"],
    ),
    "D008881": DiseaseEntry(
        mesh_descriptor_uid="D008881",
        name="Migraine",
        segment=Segment.NEUROLOGY,
        synonyms=["Migraine Disorders"],
    ),
    "D057180": DiseaseEntry(
        mesh_descriptor_uid="D057180",
        name="Frontotemporal Dementia",
        segment=Segment.NEUROLOGY,
        synonyms=["FTD"],
    ),

    # ==========================================================================
    # NEUROSCIENCE - PSYCHIATRY
    # ==========================================================================
    "D003865": DiseaseEntry(
        mesh_descriptor_uid="D003865",
        name="Major Depressive Disorder",
        segment=Segment.PSYCHIATRY,
        synonyms=["MDD", "Depression", "Clinical Depression"],
    ),
    "D012559": DiseaseEntry(
        mesh_descriptor_uid="D012559",
        name="Schizophrenia",
        segment=Segment.PSYCHIATRY,
        synonyms=[],
    ),
    "D001714": DiseaseEntry(
        mesh_descriptor_uid="D001714",
        name="Bipolar Disorder",
        segment=Segment.PSYCHIATRY,
        synonyms=["Manic-Depressive Disorder"],
    ),
    "D001008": DiseaseEntry(
        mesh_descriptor_uid="D001008",
        name="Anxiety Disorders",
        segment=Segment.PSYCHIATRY,
        synonyms=["Generalized Anxiety Disorder", "GAD"],
    ),
    "D013313": DiseaseEntry(
        mesh_descriptor_uid="D013313",
        name="PTSD",
        segment=Segment.PSYCHIATRY,
        synonyms=["Post-Traumatic Stress Disorder", "Stress Disorders, Post-Traumatic"],
    ),
    "D000067877": DiseaseEntry(
        mesh_descriptor_uid="D000067877",
        name="Autism Spectrum Disorder",
        segment=Segment.PSYCHIATRY,
        synonyms=["ASD", "Autism"],
    ),
    "D001289": DiseaseEntry(
        mesh_descriptor_uid="D001289",
        name="ADHD",
        segment=Segment.PSYCHIATRY,
        synonyms=["Attention Deficit Hyperactivity Disorder"],
    ),

    # ==========================================================================
    # INFECTIOUS DISEASES - VIRAL & VACCINES
    # ==========================================================================
    "D015658": DiseaseEntry(
        mesh_descriptor_uid="D015658",
        name="HIV/AIDS",
        segment=Segment.VIRAL_VACCINES,
        synonyms=["HIV Infections", "Acquired Immunodeficiency Syndrome"],
    ),
    "D006509": DiseaseEntry(
        mesh_descriptor_uid="D006509",
        name="Hepatitis B",
        segment=Segment.VIRAL_VACCINES,
        synonyms=["HBV", "Hepatitis B, Chronic"],
    ),
    "D006526": DiseaseEntry(
        mesh_descriptor_uid="D006526",
        name="Hepatitis C",
        segment=Segment.VIRAL_VACCINES,
        synonyms=["HCV", "Hepatitis C, Chronic"],
    ),
    "D000086382": DiseaseEntry(
        mesh_descriptor_uid="D000086382",
        name="COVID-19",
        segment=Segment.VIRAL_VACCINES,
        synonyms=["SARS-CoV-2 Infection", "Coronavirus Disease 2019"],
    ),
    "D007251": DiseaseEntry(
        mesh_descriptor_uid="D007251",
        name="Influenza",
        segment=Segment.VIRAL_VACCINES,
        synonyms=["Flu", "Influenza, Human"],
    ),
    "D018357": DiseaseEntry(
        mesh_descriptor_uid="D018357",
        name="RSV Infection",
        segment=Segment.VIRAL_VACCINES,
        synonyms=["Respiratory Syncytial Virus Infections"],
    ),
    "D006562": DiseaseEntry(
        mesh_descriptor_uid="D006562",
        name="Herpes Zoster",
        segment=Segment.VIRAL_VACCINES,
        synonyms=["Shingles"],
    ),

    # ==========================================================================
    # INFECTIOUS DISEASES - BACTERIAL & FUNGAL
    # ==========================================================================
    "D014376": DiseaseEntry(
        mesh_descriptor_uid="D014376",
        name="Tuberculosis",
        segment=Segment.BACTERIAL_FUNGAL,
        synonyms=["TB"],
    ),
    "D001424": DiseaseEntry(
        mesh_descriptor_uid="D001424",
        name="Bacterial Infections",
        segment=Segment.BACTERIAL_FUNGAL,
        synonyms=[],
    ),
    "D009181": DiseaseEntry(
        mesh_descriptor_uid="D009181",
        name="Fungal Infections",
        segment=Segment.BACTERIAL_FUNGAL,
        synonyms=["Mycoses"],
    ),

    # ==========================================================================
    # RARE & GENETIC - MONOGENIC RARE
    # ==========================================================================
    "D003550": DiseaseEntry(
        mesh_descriptor_uid="D003550",
        name="Cystic Fibrosis",
        segment=Segment.MONOGENIC_RARE,
        synonyms=["CF"],
    ),
    "D020388": DiseaseEntry(
        mesh_descriptor_uid="D020388",
        name="Duchenne Muscular Dystrophy",
        segment=Segment.MONOGENIC_RARE,
        synonyms=["DMD", "Muscular Dystrophy, Duchenne"],
    ),
    "D006467": DiseaseEntry(
        mesh_descriptor_uid="D006467",
        name="Hemophilia A",
        segment=Segment.MONOGENIC_RARE,
        synonyms=["Factor VIII Deficiency"],
    ),
    "D002836": DiseaseEntry(
        mesh_descriptor_uid="D002836",
        name="Hemophilia B",
        segment=Segment.MONOGENIC_RARE,
        synonyms=["Factor IX Deficiency", "Christmas Disease"],
    ),
    "D000755": DiseaseEntry(
        mesh_descriptor_uid="D000755",
        name="Sickle Cell Disease",
        segment=Segment.MONOGENIC_RARE,
        synonyms=["Sickle Cell Anemia", "Anemia, Sickle Cell"],
    ),
    "D013087": DiseaseEntry(
        mesh_descriptor_uid="D013087",
        name="Spinal Muscular Atrophy",
        segment=Segment.MONOGENIC_RARE,
        synonyms=["SMA"],
    ),
    "D006432": DiseaseEntry(
        mesh_descriptor_uid="D006432",
        name="Hereditary Hemochromatosis",
        segment=Segment.MONOGENIC_RARE,
        synonyms=["Hemochromatosis"],
    ),
    "D016464": DiseaseEntry(
        mesh_descriptor_uid="D016464",
        name="Fabry Disease",
        segment=Segment.MONOGENIC_RARE,
        synonyms=["Alpha-Galactosidase A Deficiency"],
    ),
    "D005776": DiseaseEntry(
        mesh_descriptor_uid="D005776",
        name="Gaucher Disease",
        segment=Segment.MONOGENIC_RARE,
        synonyms=[],
    ),

    # ==========================================================================
    # OPHTHALMOLOGY - RETINAL DISEASE
    # ==========================================================================
    "D008268": DiseaseEntry(
        mesh_descriptor_uid="D008268",
        name="Age-Related Macular Degeneration",
        segment=Segment.RETINAL_DISEASE,
        synonyms=["AMD", "Macular Degeneration"],
    ),
    "D003930": DiseaseEntry(
        mesh_descriptor_uid="D003930",
        name="Diabetic Retinopathy",
        segment=Segment.RETINAL_DISEASE,
        synonyms=["DR"],
    ),
    "D005901": DiseaseEntry(
        mesh_descriptor_uid="D005901",
        name="Glaucoma",
        segment=Segment.RETINAL_DISEASE,
        synonyms=[],
    ),
    "D012173": DiseaseEntry(
        mesh_descriptor_uid="D012173",
        name="Retinitis Pigmentosa",
        segment=Segment.RETINAL_DISEASE,
        synonyms=["RP"],
    ),
    "D058499": DiseaseEntry(
        mesh_descriptor_uid="D058499",
        name="Diabetic Macular Edema",
        segment=Segment.RETINAL_DISEASE,
        synonyms=["DME"],
    ),

    # ==========================================================================
    # SPECIALTY & OTHER - RESPIRATORY
    # ==========================================================================
    "D001249": DiseaseEntry(
        mesh_descriptor_uid="D001249",
        name="Asthma",
        segment=Segment.RESPIRATORY,
        synonyms=[],
    ),
    "D029424": DiseaseEntry(
        mesh_descriptor_uid="D029424",
        name="COPD",
        segment=Segment.RESPIRATORY,
        synonyms=["Chronic Obstructive Pulmonary Disease", "Pulmonary Disease, Chronic Obstructive"],
    ),
    "D054990": DiseaseEntry(
        mesh_descriptor_uid="D054990",
        name="Idiopathic Pulmonary Fibrosis",
        segment=Segment.RESPIRATORY,
        synonyms=["IPF"],
    ),

    # ==========================================================================
    # SPECIALTY & OTHER - WOMEN'S HEALTH
    # ==========================================================================
    "D004715": DiseaseEntry(
        mesh_descriptor_uid="D004715",
        name="Endometriosis",
        segment=Segment.WOMENS_HEALTH,
        synonyms=[],
    ),
    "D007247": DiseaseEntry(
        mesh_descriptor_uid="D007247",
        name="Infertility",
        segment=Segment.WOMENS_HEALTH,
        synonyms=["Infertility, Female"],
    ),
    "D011085": DiseaseEntry(
        mesh_descriptor_uid="D011085",
        name="Polycystic Ovary Syndrome",
        segment=Segment.WOMENS_HEALTH,
        synonyms=["PCOS"],
    ),
}


# ============================================================================
# HIERARCHY DATA CLASS
# ============================================================================

@dataclass
class DiseaseHierarchy:
    """Complete hierarchical disease classification."""
    mesh_descriptor_uid: str
    disease_name: str
    therapeutic_area: str   # L1
    segment: str            # L2
    market_driver_anchor: str  # L3 (same as disease_name)
    hierarchy_path: List[str] = field(default_factory=list)
    synonyms: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mesh_descriptor_uid": self.mesh_descriptor_uid,
            "disease_name": self.disease_name,
            "therapeutic_area": self.therapeutic_area,
            "segment": self.segment,
            "market_driver_anchor": self.market_driver_anchor,
            "hierarchy_path": self.hierarchy_path,
            "synonyms": self.synonyms,
        }


# ============================================================================
# LOOKUP FUNCTIONS
# ============================================================================

def get_disease_by_mesh_uid(mesh_uid: str) -> Optional[DiseaseHierarchy]:
    """
    Get disease hierarchy by MeSH Descriptor UID.

    Args:
        mesh_uid: MeSH Descriptor UID (D######)

    Returns:
        DiseaseHierarchy or None if not found
    """
    # Normalize UID format
    if not mesh_uid.startswith("D"):
        mesh_uid = f"D{mesh_uid}"

    entry = DISEASE_TAXONOMY.get(mesh_uid)
    if not entry:
        logger.debug(f"MeSH UID {mesh_uid} not found in taxonomy")
        return None

    return DiseaseHierarchy(
        mesh_descriptor_uid=entry.mesh_descriptor_uid,
        disease_name=entry.name,
        therapeutic_area=entry.therapeutic_area.value,
        segment=entry.segment.value,
        market_driver_anchor=entry.name,
        hierarchy_path=[
            entry.therapeutic_area.value,
            entry.segment.value,
            entry.name
        ],
        synonyms=entry.synonyms,
    )


def get_diseases_by_segment(segment: Segment) -> List[DiseaseHierarchy]:
    """
    Get all diseases in a segment.

    Args:
        segment: Segment enum value

    Returns:
        List of DiseaseHierarchy objects
    """
    results = []
    for entry in DISEASE_TAXONOMY.values():
        if entry.segment == segment:
            hierarchy = get_disease_by_mesh_uid(entry.mesh_descriptor_uid)
            if hierarchy:
                results.append(hierarchy)
    return sorted(results, key=lambda h: h.disease_name)


def get_diseases_by_therapeutic_area(ta: TherapeuticArea) -> List[DiseaseHierarchy]:
    """
    Get all diseases in a therapeutic area.

    Args:
        ta: TherapeuticArea enum value

    Returns:
        List of DiseaseHierarchy objects
    """
    results = []
    for entry in DISEASE_TAXONOMY.values():
        if entry.therapeutic_area == ta:
            hierarchy = get_disease_by_mesh_uid(entry.mesh_descriptor_uid)
            if hierarchy:
                results.append(hierarchy)
    return sorted(results, key=lambda h: (h.segment, h.disease_name))


def search_diseases(query: str, limit: int = 20) -> List[DiseaseHierarchy]:
    """
    Search for diseases by name or synonym.

    Args:
        query: Search query (case-insensitive)
        limit: Maximum results

    Returns:
        List of matching DiseaseHierarchy objects
    """
    query_lower = query.lower()
    results = []

    for entry in DISEASE_TAXONOMY.values():
        # Check main name
        if query_lower in entry.name.lower():
            hierarchy = get_disease_by_mesh_uid(entry.mesh_descriptor_uid)
            if hierarchy:
                results.append((0, hierarchy))  # Priority 0 for name match
            continue

        # Check synonyms
        for synonym in entry.synonyms:
            if query_lower in synonym.lower():
                hierarchy = get_disease_by_mesh_uid(entry.mesh_descriptor_uid)
                if hierarchy:
                    results.append((1, hierarchy))  # Priority 1 for synonym match
                break

    # Sort by priority, then alphabetically
    results.sort(key=lambda x: (x[0], x[1].disease_name))
    return [r[1] for r in results[:limit]]


def get_hierarchy_path(mesh_uid: str) -> str:
    """
    Get human-readable hierarchy path.

    Args:
        mesh_uid: MeSH Descriptor UID

    Returns:
        String like "Oncology > Solid Tumors > Lung Cancer"
    """
    hierarchy = get_disease_by_mesh_uid(mesh_uid)
    if not hierarchy:
        return f"Unknown ({mesh_uid})"
    return " > ".join(hierarchy.hierarchy_path)


def get_all_therapeutic_areas() -> List[str]:
    """Get all therapeutic area names."""
    return [ta.value for ta in TherapeuticArea]


def get_segments_for_ta(ta: TherapeuticArea) -> List[str]:
    """Get all segments for a therapeutic area."""
    return [
        segment.value
        for segment, parent_ta in SEGMENT_TO_TA.items()
        if parent_ta == ta
    ]


# ============================================================================
# DATABASE INTEGRATION
# ============================================================================

def populate_taxonomy_mappings(cursor: Any) -> Dict[str, int]:
    """
    Populate therapeutic_area_mapping table with taxonomy.

    Args:
        cursor: Database cursor

    Returns:
        Dict with counts of mappings created per TA
    """
    stats = {}

    for mesh_uid, entry in DISEASE_TAXONOMY.items():
        ta_code = _ta_to_code(entry.therapeutic_area)
        try:
            cursor.execute("""
                INSERT INTO therapeutic_area_mapping (
                    ta_code, ontology_type, ontology_value, priority, notes
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ontology_type, ontology_value) DO NOTHING
            """, (
                ta_code,
                'mesh_descriptor',
                mesh_uid,
                100,
                f'{entry.segment.value}: {entry.name}'
            ))
            stats[ta_code] = stats.get(ta_code, 0) + 1
        except Exception as e:
            logger.warning(f"Error inserting mapping for {mesh_uid}: {e}")

    logger.info(f"Populated taxonomy mappings: {stats}")
    return stats


def _ta_to_code(ta: TherapeuticArea) -> str:
    """Convert TherapeuticArea enum to short code."""
    mapping = {
        TherapeuticArea.ONCOLOGY: "ONC",
        TherapeuticArea.IMMUNOLOGY_INFLAMMATION: "IMM",
        TherapeuticArea.CARDIOMETABOLIC_RENAL: "CMR",
        TherapeuticArea.NEUROSCIENCE: "NEU",
        TherapeuticArea.INFECTIOUS_DISEASES: "ID",
        TherapeuticArea.RARE_GENETIC: "RARE",
        TherapeuticArea.OPHTHALMOLOGY: "OPH",
        TherapeuticArea.SPECIALTY_OTHER: "OTHER",
    }
    return mapping.get(ta, "OTHER")


# ============================================================================
# TAXONOMY STATISTICS
# ============================================================================

def get_taxonomy_stats() -> Dict[str, Any]:
    """Get statistics about the taxonomy."""
    ta_counts = {}
    segment_counts = {}

    for entry in DISEASE_TAXONOMY.values():
        ta = entry.therapeutic_area.value
        segment = entry.segment.value
        ta_counts[ta] = ta_counts.get(ta, 0) + 1
        segment_counts[segment] = segment_counts.get(segment, 0) + 1

    return {
        "total_diseases": len(DISEASE_TAXONOMY),
        "therapeutic_areas": len(TherapeuticArea),
        "segments": len(Segment),
        "diseases_by_ta": ta_counts,
        "diseases_by_segment": segment_counts,
    }
