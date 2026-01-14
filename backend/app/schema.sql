-- BioGraph minimal schema v0
create table if not exists entity (
 id            bigserial primary key,
 kind          text not null,                 -- drug, company, target, disease, trial, publication, patent, person, grant
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