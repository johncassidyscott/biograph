# BioGraph Build Instructions

## Running the Data Load

Due to GitHub Codespaces network restrictions, the build must run on your local machine or an unrestricted environment.

### Prerequisites

1. **Python 3.11+** installed
2. **Network access** to external APIs (ClinicalTrials.gov, ChEMBL, PubMed, etc.)
3. **Neon database credentials** (see below)

### Setup Steps

1. **Clone and checkout the branch:**
   ```bash
   git clone https://github.com/johncassidyscott/biograph.git
   cd biograph
   git checkout claude/review-progress-3LDNf
   git pull origin claude/review-progress-3LDNf
   ```

2. **Create .env file with Neon credentials:**
   ```bash
   cd backend
   echo "DATABASE_URL=postgresql://neondb_owner:npg_meyxk4t0dwXI@ep-spring-art-aheyxuga-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require" > .env
   ```

3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Reset database (creates clean schema):**
   ```bash
   python reset_db.py
   ```

5. **Build the knowledge graph:**
   ```bash
   python build_graph.py
   ```

### What the Build Does

The build runs 11 steps:

1. **Load MeSH Diseases** (~30K entities from 2026 MeSH)
2. **Load ChEMBL Drugs & Targets** (POC drug list with mechanisms)
3. **Load Clinical Trials** (ClinicalTrials.gov API - with entity resolution!)
4. **Discover Companies** (auto-discovered from trials)
5. **Load OpenTargets** (drug-disease associations)
6. **Infer Drug-Disease** (indirect relationships)
7. **Load PubMed** (publications for POC drugs)
8. **Load FDA Approvals** (regulatory data)
9. **Load Patents** (USPTO data)
10. **Load Preprints** (bioRxiv/medRxiv)
11. **Load News** (RSS feeds with automated MeSH indexing)

### Expected Results

- **Entities:** ~50-60K (mostly diseases)
- **Edges:** ~150-200K (all with confidence scores)
- **Build time:** ~20-30 minutes
- **Database size:** ~500MB-1GB

### Key Features Implemented

✅ **Entity Resolution During Ingestion**
- No post-processing deduplication needed
- Canonical ID hierarchy (ChEMBL > DRUG, MeSH > CONDITION, CIK > COMPANY)
- Confidence scores on all edges (0.0-1.0)
- Multi-strategy resolution: exact ID → name → alias → fuzzy → create new

✅ **MeSH Indexing for News**
- Automated term assignment like PubMed
- Enables semantic search across news articles
- Links news to disease entities in the graph

✅ **Discovery-Driven Architecture**
- Companies/researchers discovered from trials, not pre-selected
- Entities emerge organically from data sources

### Troubleshooting

**If database connection fails:**
- Verify Neon credentials in `.env`
- Check network can reach `ep-spring-art-aheyxuga-pooler.c-3.us-east-1.aws.neon.tech`
- Try: `ping ep-spring-art-aheyxuga-pooler.c-3.us-east-1.aws.neon.tech`

**If API calls fail:**
- Check network firewall allows HTTPS to:
  - `clinicaltrials.gov`
  - `www.ebi.ac.uk` (ChEMBL)
  - `eutils.ncbi.nlm.nih.gov` (PubMed)
- Corporate networks may require proxy configuration

**If build errors occur:**
- Check `build_output.log` for detailed errors
- Most steps gracefully handle missing data
- Build can be resumed by rerunning `python build_graph.py`

### After Build Completes

Query your knowledge graph:

```bash
# Start the API server
cd backend
uvicorn app.main:app --reload

# Test queries at:
http://localhost:8000/docs
```

### Files Modified

All code is on branch `claude/review-progress-3LDNf`:

- `entity_resolver.py` - Entity resolution system
- `loaders/load_ctgov.py` - Clinical trials with resolution
- `loaders/load_news.py` - News with MeSH indexing
- `build_graph.py` - 11-step pipeline
- `app/schema.sql` - Updated schema (confidence scores, news tables)

### Next Steps (Future)

1. Add pgvector extension + generate embeddings
2. Build RAG chat endpoint
3. Add graph visualization to UI
4. Add monitoring/alerts system
