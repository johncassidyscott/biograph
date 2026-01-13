-- BioGraph minimal schema v0
create table if not exists entity (
 id            bigserial primary key,
 kind          text not null,                 -- drug, company, target, disease, trial, publication, filing, patent
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