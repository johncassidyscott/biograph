# BioGraph Backend

Life Sciences Knowledge Graph - POC Implementation

## Quick Start

### 1. Set up environment

```bash
# Install dependencies
pip install -r requirements.txt

# Set DATABASE_URL
export DATABASE_URL='postgresql://user:pass@host:5432/dbname?sslmode=require'
```

### 2. Initialize the database

```bash
# Create schema
psql $DATABASE_URL -f app/schema.sql
```

### 3. Build the complete POC graph

```bash
# Run all loaders in sequence
python3 build_graph.py
```

This will:
1. Load ~30,000 MeSH disease entities
2. Load 12 key drugs + targets from ChEMBL
3. Load clinical trials for obesity, Alzheimer's, and KRAS oncology
4. Create drug-target-disease relationships from OpenTargets

**Expected result:** ~50K entities, ~100K edges

### 4. Start the API

```bash
./dev.sh
# or
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Visit: http://localhost:8000

---

## Individual Loaders

Run loaders individually if needed:

### Load MeSH diseases
```bash
python3 -m loaders.load_mesh
```
Loads ~30K disease entities from MeSH 2026 descriptors.

### Load ChEMBL drugs
```bash
python3 -m loaders.load_chembl
```
Loads POC drugs: GLP-1 agonists, Alzheimer's drugs, KRAS inhibitors.

### Load Clinical Trials
```bash
python3 -m loaders.load_ctgov
```
Loads trials updated Jan 2024 - Jan 2025 for POC diseases.

### Load OpenTargets associations
```bash
python3 -m loaders.load_opentargets
```
Links drugs, targets, and diseases via evidence.

---

## Verify Data

Check what's loaded:

```bash
# Quick stats
python3 check_ctgov_data.py

# Or query directly
psql $DATABASE_URL -c "
SELECT kind, COUNT(*)
FROM entity
GROUP BY kind
ORDER BY count DESC;
"
```

---

## API Endpoints

- `GET /` - Web UI
- `GET /docs` - Interactive API docs
- `GET /entities?kind=drug&limit=50` - List entities
- `GET /edges?predicate=targets&limit=100` - List edges
- `POST /seed` - Seed sample data (optional)

---

## POC Scope

**Disease areas:**
- Obesity/Metabolic
- Alzheimer's Disease
- KRAS Oncology

**Time window:** Jan 2024 - Jan 2025

**Target:** ~300K triples (realistic with current loaders)

---

## Troubleshooting

**Database connection fails:**
- Verify DATABASE_URL is set correctly
- Check network access to Neon/PostgreSQL

**Loader fails:**
- Check internet connection (loaders fetch from external APIs)
- APIs have rate limits - loaders include polite delays
- Run loaders one at a time if needed

**No data returned:**
- Run `build_graph.py` first to populate the database
- Check that schema was created: `psql $DATABASE_URL -c "\dt"`

---

## Next Steps

1. **More drugs:** Add more drugs to `build_graph.py` drug list
2. **More trials:** Expand queries in `load_ctgov.py`
3. **Companies:** Add SEC EDGAR loader for sponsor companies
4. **Publications:** Add PubMed loader for recent papers
5. **Better UI:** Add graph visualization (vis.js, Cytoscape.js)

---

## Architecture

```
Postgres (system of record)
  ├─ entity table (drugs, targets, diseases, trials, companies)
  ├─ edge table (relationships with provenance)
  ├─ alias table (synonyms for entity matching)
  └─ trial table (CT.gov facts)

FastAPI (REST API + simple UI)

Loaders (Python scripts that call external APIs)
  ├─ MeSH (diseases from NLM)
  ├─ ChEMBL (drugs + targets from EMBL-EBI)
  ├─ ClinicalTrials.gov (trials)
  └─ OpenTargets (drug-target-disease associations)
```

---

Built with Claude Code ✨
