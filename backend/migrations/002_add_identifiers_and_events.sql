-- Migration 002: Add entity identifiers, classifications, and events

-- Entity external identifiers (LEI, PermID, OpenCorporates, Wikidata, etc.)
CREATE TABLE IF NOT EXISTS entity_identifier (
    entity_id       BIGINT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    identifier_type TEXT NOT NULL,              -- 'lei', 'permid', 'opencorporates', 'wikidata_qid', 'sec_cik', 'ticker'
    identifier      TEXT NOT NULL,              -- The actual identifier value
    source          TEXT,                       -- Where we got it: 'wikidata', 'manual', 'gleif', 'sec'
    verified_at     TIMESTAMPTZ,                -- When it was last verified
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_id, identifier_type)
);
CREATE INDEX IF NOT EXISTS entity_identifier_type_idx ON entity_identifier(identifier_type);
CREATE INDEX IF NOT EXISTS entity_identifier_value_idx ON entity_identifier(identifier);

-- Entity industry classifications (NAICS, SIC)
CREATE TABLE IF NOT EXISTS entity_classification (
    entity_id           BIGINT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    classification_type TEXT NOT NULL,          -- 'naics', 'sic'
    code                TEXT NOT NULL,          -- '325412', '2834'
    description         TEXT,                   -- Human-readable description
    is_primary          BOOLEAN DEFAULT FALSE,  -- Primary classification for this entity
    source              TEXT,                   -- 'sec', 'census', 'wikidata', 'manual'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_id, classification_type, code)
);
CREATE INDEX IF NOT EXISTS entity_classification_type_idx ON entity_classification(classification_type);
CREATE INDEX IF NOT EXISTS entity_classification_code_idx ON entity_classification(code);

-- Events table (funding rounds, clinical trials, regulatory approvals, M&A, etc.)
CREATE TABLE IF NOT EXISTS event (
    id              BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,              -- 'series_a', 'fda_approval', 'phase3_results', 'earnings', 'ipo'
    event_category  TEXT NOT NULL,              -- 'funding', 'clinical', 'regulatory', 'corporate', 'business_development'
    name            TEXT NOT NULL,              -- Human-readable event name
    description     TEXT,                       -- Event details
    event_date      DATE,                       -- When the event occurred
    announced_date  DATE,                       -- When it was announced (may differ from event_date)
    amount_usd      NUMERIC(15,2),              -- For funding events: amount in USD
    source          TEXT,                       -- 'sec_8k', 'crunchbase', 'clinicaltrials_gov', 'fda', 'manual'
    source_url      TEXT,                       -- Link to source
    metadata        JSONB,                      -- Flexible storage for event-specific data
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS event_type_idx ON event(event_type);
CREATE INDEX IF NOT EXISTS event_category_idx ON event(event_category);
CREATE INDEX IF NOT EXISTS event_date_idx ON event(event_date DESC);
CREATE INDEX IF NOT EXISTS event_metadata_idx ON event USING GIN (metadata);

-- Event participants (which entities are involved in this event)
CREATE TABLE IF NOT EXISTS event_participant (
    event_id        BIGINT NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    entity_id       BIGINT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,              -- 'subject', 'investor', 'acquirer', 'target', 'sponsor'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (event_id, entity_id, role)
);
CREATE INDEX IF NOT EXISTS event_participant_event_idx ON event_participant(event_id);
CREATE INDEX IF NOT EXISTS event_participant_entity_idx ON event_participant(entity_id);
CREATE INDEX IF NOT EXISTS event_participant_role_idx ON event_participant(role);

-- Event relationships (events can relate to other events)
CREATE TABLE IF NOT EXISTS event_relation (
    parent_event_id BIGINT NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    child_event_id  BIGINT NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL,              -- 'follows', 'triggers', 'part_of', 'related_to'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (parent_event_id, child_event_id, relation_type),
    CHECK (parent_event_id != child_event_id)
);
CREATE INDEX IF NOT EXISTS event_relation_parent_idx ON event_relation(parent_event_id);
CREATE INDEX IF NOT EXISTS event_relation_child_idx ON event_relation(child_event_id);
