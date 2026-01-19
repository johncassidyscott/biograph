# BioGraph CSV Schemas

This document defines the exact CSV formats for loading data into BioGraph.

## Company Universe CSV

**Loader**: `scripts/load_company_universe.py`

### Required Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `cik` | string | SEC Central Index Key (10 digits, zero-padded) | `0000078003` |
| `company_name` | string | SEC legal name | `PFIZER INC` |

### Optional Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `ticker` | string | Stock ticker symbol | `PFE` |
| `exchange` | string | Stock exchange | `NYSE` |
| `universe_id` | string | Universe membership ID | `xbi` |
| `revenue_usd` | decimal | Annual revenue in USD | `81288000000` |
| `employees` | integer | Employee count | `83000` |

### Example CSV

```csv
cik,company_name,ticker,exchange,universe_id,revenue_usd,employees
0000078003,PFIZER INC,PFE,NYSE,xbi,81288000000,83000
0000310158,JOHNSON & JOHNSON,JNJ,NYSE,xbi,94943000000,140000
0000014272,AMGEN INC,AMGN,NASDAQ,xbi,25424000000,26100
0000318154,REGENERON PHARMACEUTICALS INC,REGN,NASDAQ,xbi,12172000000,11600
0000885590,GILEAD SCIENCES INC,GILD,NASDAQ,xbi,24426000000,17000
```

### Usage

```bash
# Set database connection
export DATABASE_URL="postgresql://user:pass@localhost/biograph"

# Dry run (no changes)
python scripts/load_company_universe.py --csv data/universe.csv --dry-run

# Actual load
python scripts/load_company_universe.py --csv data/universe.csv
```

### What Gets Created

For each row in the CSV:

1. **`company`** record with SEC metadata
2. **`issuer`** record with stable ID (`ISS_{CIK}`)
3. **`universe_membership`** (if `universe_id` provided)

---

## Drug Program CSV (Future)

**Loader**: `scripts/load_drug_programs.py` (not yet implemented)

### Required Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `cik` | string | Company CIK | `0000078003` |
| `program_slug` | string | Unique program identifier | `paxlovid` |
| `program_name` | string | Display name | `Paxlovid (nirmatrelvir/ritonavir)` |

### Optional Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `modality` | string | Drug modality | `small_molecule` |
| `stage` | string | Development stage | `marketed` |
| `primary_indication` | string | Primary disease | `COVID-19` |

### Example CSV

```csv
cik,program_slug,program_name,modality,stage,primary_indication
0000078003,paxlovid,Paxlovid,small_molecule,marketed,COVID-19
0000078003,comirnaty,Comirnaty,mrna_vaccine,marketed,COVID-19
0000014272,otezla,Otezla,small_molecule,marketed,Psoriasis
```

---

## Target Linkage CSV (Future)

**Loader**: `scripts/load_target_linkages.py` (not yet implemented)

### Required Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `cik` | string | Company CIK | `0000078003` |
| `program_slug` | string | Program identifier | `paxlovid` |
| `target_id` | string | OpenTargets ID | `ENSG00000130203` |
| `evidence_source` | string | Evidence source | `sec_edgar` |

### Optional Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `evidence_uri` | string | Link to evidence | `https://sec.gov/...` |
| `confidence` | string | Confidence band | `HIGH` |

---

## Database Tables Reference

### `company` Table

```sql
CREATE TABLE company (
    cik                 TEXT PRIMARY KEY,
    sec_legal_name      TEXT NOT NULL,
    ticker              TEXT,
    exchange            TEXT,
    revenue_usd         BIGINT,
    employees           INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

### `issuer` Table

```sql
CREATE TABLE issuer (
    issuer_id           TEXT PRIMARY KEY,  -- Format: ISS_{CIK}
    primary_cik         TEXT NOT NULL REFERENCES company(cik),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
```

### `universe_membership` Table

```sql
CREATE TABLE universe_membership (
    id                  BIGSERIAL PRIMARY KEY,
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id),
    universe_id         TEXT NOT NULL,     -- e.g., 'xbi', 'ibb', 'custom_2024'
    start_date          DATE NOT NULL,
    end_date            DATE,              -- NULL = current member
    UNIQUE(issuer_id, universe_id)
);
```

### `drug_program` Table

```sql
CREATE TABLE drug_program (
    drug_program_id     TEXT PRIMARY KEY,  -- Format: CIK:{cik}:PROG:{slug}
    issuer_id           TEXT NOT NULL REFERENCES issuer(issuer_id),
    slug                TEXT NOT NULL,
    name                TEXT NOT NULL,
    modality            TEXT,
    stage               TEXT,
    primary_indication  TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Validation Rules

### CIK Formatting
- Must be numeric
- Zero-padded to 10 digits
- Example: `78003` → `0000078003`

### Issuer ID Generation
- Format: `ISS_{CIK}`
- Example: `ISS_0000078003`

### Drug Program ID Generation
- Format: `CIK:{cik}:PROG:{slug}`
- Example: `CIK:0000078003:PROG:paxlovid`

### Universe IDs
Common values:
- `xbi` - SPDR S&P Biotech ETF
- `ibb` - iShares Biotechnology ETF
- `custom_{year}` - Custom universes
