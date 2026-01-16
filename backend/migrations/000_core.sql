CREATE TABLE mesh_descriptor (
    ui TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE mesh_tree (
    ui TEXT REFERENCES mesh_descriptor(ui) ON DELETE CASCADE,
    tree_number TEXT NOT NULL,
    PRIMARY KEY (ui, tree_number)
);

CREATE TABLE mesh_alias (
    ui TEXT REFERENCES mesh_descriptor(ui) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    PRIMARY KEY (ui, alias)
);

CREATE TABLE entity (
    id SERIAL PRIMARY KEY,
    kind TEXT,
    canonical_id TEXT,
    name TEXT NOT NULL,
    type TEXT,
    source TEXT,
    mesh_ui TEXT REFERENCES mesh_descriptor(ui),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(kind, canonical_id)
);

CREATE TABLE alias (
    entity_id INT REFERENCES entity(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    source TEXT,
    PRIMARY KEY (entity_id, alias)
);

CREATE TABLE edge (
    id SERIAL PRIMARY KEY,
    src_id INT REFERENCES entity(id) ON DELETE CASCADE,
    dst_id INT REFERENCES entity(id) ON DELETE CASCADE,
    type TEXT,
    props JSONB DEFAULT '{}'::jsonb
);

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
