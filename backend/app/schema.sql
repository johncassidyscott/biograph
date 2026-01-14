-- BioGraph minimal schema v0
create table if not exists entity (
 id            bigserial primary key,
 kind          text not null,                 -- drug, company, target, disease, trial, publication, patent, person, grant, news
 canonical_id  text not null,                 -- e.g., CHEMBL:CHEMBL25, NCT:NCT01234567, MESH:D012345
 name          text not null,
 created_at    timestamptz not null default now(),
 updated_at    timestamptz not null default now(),
 unique (kind, canonical_id)
);
create index if not exists entity_kind_idx on entity(kind);
create index if not exists entity_name_idx on entity using gin (to_tsvector('english', name));
create table if not exists alias (
 id          bigserial primary key,
 entity_id   bigint not null references entity(id) on delete cascade,
 alias       text not null,
 source      text,                            -- mesh, chembl, opentargets, ctgov, manual
 created_at  timestamptz not null default now()
);
create index if not exists alias_alias_idx on alias(lower(alias));
create table if not exists edge (
 id           bigserial primary key,
 src_id       bigint not null references entity(id) on delete cascade,
 predicate    text not null,          -- e.g., targets, treats, in_trial, sponsored_by
 dst_id       bigint not null references entity(id) on delete cascade,
 source       text,                   -- mesh, chembl, ctgov, manual
 confidence   real default 1.0,       -- 0.0-1.0: relationship confidence score
 created_at   timestamptz not null default now(),
 unique (src_id, predicate, dst_id)
);
create index if not exists edge_src_idx on edge(src_id);
create index if not exists edge_dst_idx on edge(dst_id);
create index if not exists edge_pred_idx on edge(predicate);

-- MeSH foundation tables
create table if not exists mesh_descriptor (
 ui   text primary key,
 name text not null
);
create table if not exists mesh_tree (
 ui          text not null references mesh_descriptor(ui) on delete cascade,
 tree_number text not null,
 primary key (ui, tree_number)
);
create table if not exists mesh_alias (
 ui    text not null references mesh_descriptor(ui) on delete cascade,
 alias text not null,
 primary key (ui, alias)
);
create index if not exists mesh_alias_lower_idx on mesh_alias(lower(alias));
create index if not exists mesh_tree_prefix_idx on mesh_tree(tree_number);

-- ClinicalTrials.gov trial facts (queryable filters live here)
create table if not exists trial (
 nct_id                 text primary key,
 title                  text,
 overall_status         text,
 phase_raw              text,
 phase_min              int,
 study_type             text,
 start_date             date,
 primary_completion_date date,
 completion_date        date,
 last_update_posted     date,
 sponsor_name           text
);
create index if not exists trial_phase_min_idx on trial(phase_min);
create index if not exists trial_status_idx on trial(overall_status);
create index if not exists trial_last_update_idx on trial(last_update_posted);

-- News/press release articles
create table if not exists news_item (
 entity_id       bigint primary key references entity(id) on delete cascade,
 url             text not null unique,
 published_date  timestamptz,
 source          text,                   -- 'fda_rss', 'fierce_pharma', 'globenewswire', etc.
 summary         text,
 created_at      timestamptz not null default now()
);
create index if not exists news_item_published_idx on news_item(published_date desc);
create index if not exists news_item_source_idx on news_item(source);

-- MeSH indexing for news articles (like PubMed)
create table if not exists news_mesh (
 news_entity_id  bigint not null references entity(id) on delete cascade,
 mesh_ui         text not null,          -- e.g., 'D009765'
 mesh_name       text not null,          -- e.g., 'Obesity'
 confidence      real default 1.0,       -- 0.0-1.0: indexing confidence
 is_major_topic  boolean default false,  -- Main focus of article
 source          text,                   -- 'resolver', 'mti', 'deepmesh'
 indexed_at      timestamptz not null default now(),
 primary key (news_entity_id, mesh_ui)
);
create index if not exists news_mesh_ui_idx on news_mesh(mesh_ui);
create index if not exists news_mesh_major_idx on news_mesh(mesh_ui) where is_major_topic = true;
create index if not exists news_mesh_confidence_idx on news_mesh(confidence) where confidence > 0.8;

-- article_mesh: MeSH indexing for publications, preprints, and other articles
-- This table stores MeSH terms for any article-type entity (publications, news, preprints)
create table if not exists article_mesh (
 article_entity_id bigint not null references entity(id) on delete cascade,
 mesh_ui           text not null,          -- MeSH Unique ID (e.g., 'D009765')
 mesh_name         text not null,          -- MeSH descriptor name (e.g., 'Obesity')
 is_major_topic    boolean default false,  -- Y/N from PubMed or confidence-based
 confidence        real default 1.0,       -- 1.0 for NLM indexing, <1.0 for automated
 source            text,                   -- 'pubmed_nlm', 'comprehensive', 'mti'
 indexed_at        timestamptz not null default now(),
 primary key (article_entity_id, mesh_ui)
);
create index if not exists article_mesh_ui_idx on article_mesh(mesh_ui);
create index if not exists article_mesh_major_idx on article_mesh(mesh_ui) where is_major_topic = true;
create index if not exists article_mesh_entity_idx on article_mesh(article_entity_id);

-- article_mesh_qualifier: MeSH qualifiers/subheadings (e.g., "diagnosis", "therapy")
-- Enables precise filtering like PubMed (e.g., "Obesity/diagnosis", "Obesity/drug therapy")
create table if not exists article_mesh_qualifier (
 article_entity_id bigint not null,
 mesh_ui           text not null,
 qualifier_ui      text not null,          -- Qualifier ID (e.g., 'Q000175' for diagnosis)
 qualifier_name    text not null,          -- Qualifier name (e.g., 'diagnosis')
 is_major          boolean default false,  -- Major focus
 foreign key (article_entity_id, mesh_ui) references article_mesh(article_entity_id, mesh_ui) on delete cascade,
 primary key (article_entity_id, mesh_ui, qualifier_ui)
);
create index if not exists article_mesh_qualifier_ui_idx on article_mesh_qualifier(qualifier_ui);

-- publication_type: Store publication types (Clinical Trial, Review, Meta-Analysis, etc.)
create table if not exists publication_type (
 article_entity_id bigint not null references entity(id) on delete cascade,
 pub_type          text not null,          -- e.g., 'Clinical Trial', 'Review'
 primary key (article_entity_id, pub_type)
);
create index if not exists publication_type_idx on publication_type(pub_type);