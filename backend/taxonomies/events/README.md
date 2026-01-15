# BioGraph Events Taxonomy (DRAFT)

## Overview

This is a **DRAFT** comprehensive events taxonomy for life sciences business intelligence. It combines existing standards (where available) with novel classifications for domain-specific events.

## Structure

The taxonomy is organized into three main categories:

1. **Corporate & Financial Events** (`corporate_financial.yaml`)
   - Based on SEC Form 8-K Material Events
   - Covers earnings, M&A, bankruptcy, governance changes

2. **Funding Events** (`funding.yaml`)
   - Based on Crunchbase taxonomy + SEC Form D
   - Covers venture rounds, debt financing, public offerings

3. **Life Sciences Events** (`life_sciences.yaml`)
   - **Novel taxonomy** - no existing standard
   - Covers clinical trials, regulatory approvals, R&D milestones

## Status

**DRAFT** - Subject to revision. Not yet published as open standard.

## Sources

- SEC Form 8-K: Public Domain (US Government)
- Crunchbase Funding Types: Industry standard (public documentation)
- SEC Form D / Regulation D: Public Domain (US Government)
- Life Sciences taxonomy: BioGraph original work

## Future Considerations

- Publishing as "BioGraph Life Sciences Events Ontology (BLSEO)" under CC-BY 4.0
- Integration with FIBO for semantic relationships
- XBRL/iXBRL tagging for financial event data
- HL7 FHIR extensions for clinical events
