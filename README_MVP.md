# BioGraph MVP v8.0

**Index-anchored intelligence graph for life sciences**

> Bloomberg-thinking applied to life sciences — not a science project.

---

## What This Is

BioGraph MVP is an investor-grade knowledge graph that explains **why a life sciences company is moving**, with evidence.

**For**: Buy-side analysts, strategy/BD teams, corporate development
**NOT for**: Bench scientists, bioinformatics teams, clinical statisticians

---

## Core Value Proposition

**Clean, auditable intelligence chains:**

```
Company → Drug/Program → Target → Disease
```

With evidence you can trace to the source.

- **Index-anchored**: Only curated, CIK-identified issuers
- **Evidence-first**: Every edge has source, date, confidence, license
- **Time-aware**: Know what changed and when
- **No graph soup**: Fixed explanation templates only

---

## Quick Start

### 1. Prerequisites

- Python 3.10+
- PostgreSQL 14+
- `DATABASE_URL` environment variable set

### 2. Initialize Database

```bash
cd backend
python build_graph_mvp.py --init
```

This creates the MVP schema (9 entity tables, evidence-first edge model).

### 3. Load Universe

Save your 246 companies as CSV following this format:

```csv
company_name,ticker,exchange,cik,universe_id,start_date,notes
Eli Lilly and Company,LLY,NYSE,0000059478,xbi,2024-01-01,Example
```

Then load:

```bash
python build_graph_mvp.py --universe data/universe.csv --phases 0
```

### 4. Run Full Pipeline

Execute all ingestion phases:

```bash
python build_graph_mvp.py --phases all
```

**Phases:**
- **Phase 0**: Universe (manual CSV)
- **Phase 1**: CIK resolution (SEC EDGAR)
- **Phase 2**: Corporate spine (filings)
- **Phase 3**: Enrichment (Wikidata)
- **Phase 4**: Asset mapping (OpenTargets)

Each phase respects SEC/Wikidata rate limits automatically.

### 5. Start API

```bash
python ../app_mvp.py
```

Navigate to `http://localhost:5000` to see the dashboard.

---

## Architecture

### Data Model (9 Entities — Hard Capped)

1. **Company** (CIK = canonical ID)
2. **Filing** (SEC EDGAR metadata)
3. **InsiderTransaction** (Form 4)
4. **Exhibit** (metadata only, no full text)
5. **Location** (GeoNames canonical)
6. **DrugProgram** (ChEMBL or internal ID)
7. **Target** (OpenTargets stable ID)
8. **Disease** (EFO/MONDO from OpenTargets)
9. **Evidence** (first-class entity)

### Evidence-First Edge Model

**Every relationship stores:**
- `source_system` (e.g., 'sec_edgar', 'opentargets')
- `source_record_id` (external identifier)
- `observed_at` (timestamp)
- `confidence` (0.0-1.0)
- `license` (e.g., 'CC0', 'Public Domain')

**No edge without provenance.**

### Fixed Explanation Chains

The MVP has **NO free graph traversal**. All queries conform to:

```
Company → DrugProgram → Target → Disease
```

Implemented as materialized view `explanation_chain` for performance.

---

## API Endpoints

### List Companies
```
GET /api/companies?universe_id=xbi
```

### Company Dashboard
```
GET /api/company/{cik}
```

Returns:
- Pipeline summary (program → target → disease)
- Evidence strength
- Recent filings
- Insider transactions
- HQ location

### Explanation Chains
```
GET /api/explanation-chain/{cik}?disease_id=EFO_0000319
```

Returns the full evidence chain with source links.

### Quality Metrics
```
GET /api/quality-metrics
```

Per spec section 10.1:
- % companies with ≥1 DrugProgram (target: ≥95%)
- % drugs with Target + Disease (target: ≥90%)
- Edges without evidence (target: 0)

### Search
```
GET /api/search?q=lilly
```

Searches across companies, drugs, targets, diseases.

---

## Quality Gates

After each ingestion run, quality metrics are checked:

1. **≥95% of companies have ≥1 DrugProgram**
2. **≥90% of DrugPrograms have Target + Disease**
3. **100% of edges have source + date + license**

View quality dashboard:
```bash
python build_graph_mvp.py --quality-gates
```

---

## Data Sources (Free + Commercial-Safe)

### Corporate / Market
- **SEC EDGAR**: Filings metadata, 8-K items, XBRL highlights
- **SEC Form 4**: Insider transactions
- **SEC Exhibit Index**: Metadata only (no full text)

### Biomedical
- **Open Targets Platform**: CC0 license, target-disease associations
- **ChEMBL**: CC BY-SA 3.0, drug-target relationships

### Enrichment
- **Wikidata**: CC0, CIK joins, HQ location, revenue, employees
- **GeoNames**: CC BY 4.0, canonical location IDs

---

## Scope Contract

### What's In Scope (MVP)
- Indexed/ETF-listed US issuers (CIK-identified)
- Major SEC forms (10-K, 10-Q, 8-K)
- Form 4 insider transactions
- Drug programs with ChEMBL IDs or internal candidates
- Target-disease associations (OpenTargets)
- HQ locations (Wikidata → GeoNames)

### Explicitly Out of Scope
- Non-CIK companies
- Pathways, variants, omics
- Clinical trial arms/endpoints
- Patent claims (future phase)
- Subsidiary-level legal entities
- Free graph traversal

---

## Ingestion Scripts

### Phase 0: Universe
```bash
cd backend
python loaders/load_universe.py data/universe.csv xbi
```

### Phase 1: CIK Resolution
```bash
python loaders/resolve_cik.py xbi
```

Validates CIKs against SEC EDGAR and stores legal names.

### Phase 2: SEC Filings
```bash
python loaders/load_sec_filings.py
```

Loads filings metadata (respects 10 req/sec SEC limit).

### Phase 3: Wikidata Enrichment
```bash
python loaders/enrich_wikidata.py
```

Fetches HQ location, revenue, employees from Wikidata.

### Phase 4: OpenTargets
```bash
python loaders/load_opentargets_mvp.py
```

Loads target-disease associations for key therapeutic areas.

---

## Development

### Run Individual Phases
```bash
# Just CIK resolution
python build_graph_mvp.py --phases 1

# Corporate spine + enrichment
python build_graph_mvp.py --phases 2,3
```

### Check Quality Gates
```bash
python build_graph_mvp.py --quality-gates
```

### Refresh Explanation Chains
```sql
SELECT refresh_explanation_chain();
```

---

## Deployment

The MVP is designed for:
- **PostgreSQL** (system of record)
- **FastAPI** (API layer)
- **Static HTML** (frontend)

No complex dependencies. Deploy anywhere that runs Python + Postgres.

---

## What Makes This Commercially Novel

1. **Fixed explanation chains** (no graph soup)
2. **Evidence-first, audit-friendly** model
3. **Index-anchored** scope (investor mental model)
4. **Cross-domain joins** without R&D noise
5. **Reproducible, deterministic** ingestion
6. **Quality gates** built into pipeline

This is **Bloomberg-thinking applied to life sciences**, not a science project.

---

## Roadmap (Post-MVP)

- Form 4 insider transaction parsing
- Exhibit extraction (contract mentions)
- Patent ingestion (CPC codes)
- XBRL extraction (select concepts)
- Time-series views ("what changed since Q3?")
- Comparable company detection
- Alert system (filing triggers)

---

## License

Code: MIT
Data sources: See individual licenses (SEC = Public Domain, OpenTargets = CC0, Wikidata = CC0, ChEMBL = CC BY-SA 3.0)

---

## Support

For questions or issues, open a GitHub issue.

**Version**: 8.0-MVP
**Status**: Ready to build
**Audience**: Institutional investors, strategy, BD, CI
