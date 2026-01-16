CREATE TABLE patent (
    id SERIAL PRIMARY KEY,
    patent_number TEXT UNIQUE NOT NULL,
    publication_date DATE,
    title TEXT,
    abstract TEXT,
    cpc_codes TEXT[],
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE assignee (
    id SERIAL PRIMARY KEY,
    name_raw TEXT NOT NULL,
    name_norm TEXT,
    country TEXT,
    type TEXT,
    lei TEXT,
    cik TEXT,
    wikidata_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE patent_assignee (
    patent_id INT REFERENCES patent(id) ON DELETE CASCADE,
    assignee_id INT REFERENCES assignee(id) ON DELETE CASCADE,
    role TEXT,
    sequence INT,
    PRIMARY KEY (patent_id, assignee_id, sequence)
);

CREATE TABLE patent_drug (
    patent_id INT REFERENCES patent(id) ON DELETE CASCADE,
    chembl_id TEXT NOT NULL,
    link_type TEXT,
    PRIMARY KEY (patent_id, chembl_id)
);
