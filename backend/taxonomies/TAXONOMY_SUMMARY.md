# BioGraph Taxonomy Implementation Summary

## Status: FOUNDATION COMPLETE ✅

This document summarizes the taxonomy infrastructure created for BioGraph.

## Database Schema (Migration 002)

**File**: `backend/migrations/002_add_identifiers_and_events.sql`

### New Tables:

1. **`entity_identifier`** - External identifiers for entities
   - LEI (Legal Entity Identifier)
   - PermID (Refinitiv)
   - OpenCorporates ID
   - Wikidata QID
   - SEC CIK
   - Stock tickers

2. **`entity_classification`** - Industry classifications
   - NAICS codes
   - SIC codes
   - Primary/secondary classification support

3. **`event`** - Business, clinical, regulatory events
   - Comprehensive event tracking
   - Flexible metadata (JSONB)
   - Amount tracking (for funding)
   - Source attribution

4. **`event_participant`** - Entity-event relationships
   - Links entities to events
   - Roles (subject, investor, acquirer, etc.)

5. **`event_relation`** - Event-event relationships
   - Event sequences
   - Dependencies
   - Hierarchies

## Taxonomy Files

### Entity Taxonomies

#### 1. NAICS (North American Industry Classification System)
**File**: `backend/taxonomies/entities/naics.yaml`

**Source**: US Census Bureau (Public Domain)

**Coverage**: Life sciences focused codes including:
- Pharmaceutical Manufacturing (325411-325414)
  - 325412: Pharmaceutical Preparation Manufacturing (Pfizer, Moderna, etc.)
  - 325414: Biological Products Manufacturing (Amgen, Genentech, etc.)
- R&D (541711-541712)
  - 541711: Biotechnology Research
- Medical Devices (334510, 339112-339113)
- Healthcare Services (621511-621512)
- Consulting & Testing (541380, 541690)

#### 2. SIC (Standard Industrial Classification)
**File**: `backend/taxonomies/entities/sic.yaml`

**Source**: SEC/US Government (Public Domain)

**Purpose**: SEC EDGAR filing compatibility

**Coverage**: Life sciences codes including:
- 2834: Pharmaceutical Preparations (most common)
- 2833: Medicinal Chemicals
- 2835: Diagnostic Substances
- 2836: Biological Products
- 3841-3845: Medical Devices
- 8731: Commercial Biological Research (CROs)
- 5122: Drug Wholesale Distribution

**Note**: Legacy system (1987) but **still required by SEC** for all EDGAR filings.

### Event Taxonomies (DRAFT)

#### 1. Corporate & Financial Events
**File**: `backend/taxonomies/events/corporate_financial.yaml`

**Source**: SEC Form 8-K Material Events (Public Domain) + Industry Standards

**Coverage**:
- **SEC 8-K Section 1**: Business operations
  - Material agreements (1.01, 1.02)
  - Bankruptcy (1.03)
  - Cybersecurity incidents (1.05)

- **SEC 8-K Section 2**: Financial information
  - M&A completion (2.01)
  - Earnings announcements (2.02)
  - Debt issuance (2.03)
  - Impairments (2.06)

- **SEC 8-K Section 3**: Securities events
  - Delisting notices (3.01)
  - Private placements (3.02)

- **SEC 8-K Section 4**: Accounting
  - Auditor changes (4.01)
  - Financial restatements (4.02)

- **SEC 8-K Section 5**: Governance
  - Change of control (5.01)
  - Officer/director changes (5.02)
  - Shareholder votes (5.07)

- **Additional**: Guidance updates, dividends, credit ratings, analyst days

#### 2. Funding Events
**File**: `backend/taxonomies/events/funding.yaml`

**Sources**:
- Crunchbase Funding Types API (industry standard)
- SEC Form D / Regulation D (Public Domain)

**Coverage**:

- **Early Stage Venture**:
  - Pre-seed, Seed, Angel
  - Series A, B, C, D+
  - Corporate venture rounds

- **Alternative Financing**:
  - Convertible notes
  - SAFEs
  - Equity crowdfunding

- **Debt Financing**:
  - Venture debt
  - Credit facilities
  - Term loans

- **Public Markets**:
  - IPO, Direct listing, SPAC
  - Follow-on offerings
  - ATM offerings (critical for biotech)
  - PIPEs
  - Registered direct offerings

- **Non-Dilutive**:
  - NIH SBIR/STTR grants (Phase I, II, IIB)
  - Foundation grants
  - Revenue-based financing

- **Strategic**:
  - Strategic investments
  - Licensing upfront payments
  - Milestone payments

- **SEC Regulation D Mapping**:
  - Rule 506(b) - traditional VC
  - Rule 506(c) - general solicitation allowed
  - Regulation A+ - mini-IPO

#### 3. Life Sciences Events (NOVEL TAXONOMY)
**File**: `backend/taxonomies/events/life_sciences.yaml`

**Source**: BioGraph original work - **NO EXISTING STANDARD EXISTS**

**Status**: DRAFT - Under consideration for open publication as "BioGraph Life Sciences Events Ontology (BLSEO)"

**Coverage**:

- **Clinical Development** (Preclinical → Phase 1 → Phase 2 → Phase 3):
  - IND process (submission, clearance, clinical holds)
  - Phase initiation, enrollment, interim analyses
  - Top-line results (positive/negative/mixed)
  - Trial discontinuations
  - Full results presentations

- **Regulatory Submissions**:
  - NDA/BLA submissions
  - FDA filing acceptance/refusal
  - Priority Review, Breakthrough, Fast Track, Orphan designations
  - FDA meeting types (A, B, C)
  - Advisory Committee meetings and votes

- **Regulatory Decisions**:
  - FDA approvals/rejections (CRL)
  - Label expansions
  - International approvals (EMA, PMDA, NMPA)

- **Commercial Events**:
  - Drug launches
  - First commercial sales
  - Manufacturing partnerships
  - Supply agreements

- **Business Development**:
  - Licensing deals
  - Research collaborations
  - Co-development agreements
  - Asset acquisitions/divestitures

- **Manufacturing & Supply**:
  - Facility expansions
  - Manufacturing issues
  - FDA Form 483 / Warning Letters

- **Post-Market Safety**:
  - Safety signals
  - Black Box Warnings
  - REMS requirements
  - Product recalls
  - Market withdrawals

- **Pipeline Management**:
  - Pipeline updates
  - Program discontinuations
  - New program disclosures
  - Candidate selections

## What's Novel

### Existing Standards Used:
✅ SEC Form 8-K (public domain)
✅ NAICS/SIC (public domain)
✅ Crunchbase funding types (documented industry standard)
✅ SEC Form D/Regulation D (public domain)

### BioGraph Original Work:
⭐ **Life Sciences Events Taxonomy** - Comprehensive clinical/regulatory event classification where no standard previously existed

## Competitive Advantage

**BioGraph now has event classification that PitchBook and Bloomberg don't have:**
- Complete clinical trial milestone tracking
- Regulatory approval pathway events
- R&D pipeline transitions
- Post-market safety events specific to life sciences

## Next Steps

1. ✅ Database schema designed
2. ✅ Taxonomy files created
3. ⏳ Entity enrichment service (Wikidata SPARQL)
4. ⏳ API endpoints for identifiers and events
5. ⏳ UI updates to display new data
6. ⏳ Data loaders to populate from real sources

## Publishing Considerations

**Option 1**: Keep life sciences taxonomy proprietary (competitive advantage)

**Option 2**: Publish as "BioGraph Life Sciences Events Ontology (BLSEO)" under CC-BY 4.0
- Pros: Industry goodwill, thought leadership, cite-able, PR value
- Cons: Give away competitive advantage

**Option 3**: Hybrid - Publish core taxonomy, keep advanced classifications/relationships proprietary

## Files Created

```
backend/
├── migrations/
│   └── 002_add_identifiers_and_events.sql
└── taxonomies/
    ├── TAXONOMY_SUMMARY.md (this file)
    ├── entities/
    │   ├── naics.yaml
    │   └── sic.yaml
    └── events/
        ├── README.md
        ├── corporate_financial.yaml
        ├── funding.yaml
        └── life_sciences.yaml
```

## Usage Example

```python
# When adding Moderna to BioGraph:
entity = {
    "name": "Moderna Inc.",
    "kind": "company",
    "identifiers": {
        "lei": "549300RHD38RQKER3658",
        "permid": "5000168508",
        "opencorporates": "us_de/4389449",
        "wikidata_qid": "Q30715381",
        "sec_cik": "0001682852",
        "ticker": "MRNA"
    },
    "classifications": {
        "naics": "325412",  # Pharmaceutical Preparation Manufacturing
        "sic": "2834"       # Pharmaceutical Preparations (for SEC)
    }
}

# When tracking Series C funding:
event = {
    "event_type": "series_c",
    "event_category": "funding",
    "name": "Moderna Series C - $1.1B",
    "event_date": "2020-05-18",
    "amount_usd": 1100000000,
    "participants": [
        {"entity": "moderna", "role": "subject"},
        {"entity": "flagship_pioneering", "role": "investor"}
    ],
    "source": "sec_form_d",
    "metadata": {
        "regulation_type": "rule_506b",
        "investors_count": 15
    }
}

# When tracking FDA approval:
event = {
    "event_type": "fda_approved",
    "event_category": "regulatory",
    "name": "Spikevax (mRNA-1273) FDA Approval",
    "event_date": "2021-08-23",
    "participants": [
        {"entity": "moderna", "role": "subject"},
        {"entity": "fda", "role": "regulatory_body"}
    ],
    "source": "fda_press_release",
    "metadata": {
        "indication": "COVID-19 prevention",
        "approval_type": "full_approval",
        "priority_review": true,
        "phase3_trial": "NCT04470427"
    }
}
```

---

**Date**: 2026-01-15
**Author**: Claude (BioGraph Team)
**Status**: Foundation complete, ready for integration
