# biograph

Life Sciences Intelligence Platform

Version 7.0 — January 2026
Status: POC ready to build

⸻

1. What This Is

A life sciences knowledge graph you can explore, query, and interrogate.

Not a feed reader with a graph bolted on —
the graph is the product.

It answers:
“What do we know about X — right now, and why?”

Where X can be a drug, company, target, disease, trial, person, patent, or regulator.

⸻

2. What This Is Not

This is not:
	•	a document repository
	•	a PDF viewer
	•	a news aggregator
	•	a content platform

This is a metadata and intelligence system.

We store:
	•	entities
	•	relationships
	•	timestamps
	•	provenance
	•	document identifiers
	•	abstracts or snippets when legally allowed

We never store or redistribute:
	•	full journal articles
	•	subscription news
	•	proprietary filings

We always link to authoritative sources.

This is legally equivalent to PubMed + Crossref + Google Scholar + EDGAR — but entity-centric.

⸻

3. Core Product

Core interactions:
	1.	Entity explorer — browse entities and expand their graph
	2.	Entity pages — everything known about a drug, company, target, disease, or trial
	3.	Semantic chat — natural language → graph queries → grounded answers with citations
	4.	Timeline / feed — recent updates touching watched entities

The feed is a view of the graph, not the product.

⸻

4. Initial POC Scope

Disease areas: Obesity/Metabolic, KRAS Oncology, Alzheimer’s
Companies: ~50
Time window: Jan 2024 – Jan 2025
Graph size: ~300k triples (fits Neo4j Aura Free)

⸻

5. Entity Model

Drug — targets, treats, in_trial, developed_by
Company — develops, licenses, acquired, partners_with
Target — associated_with (disease), targeted_by
Disease — treated_by, has_trial
Trial — studies, sponsored_by, for_condition
Evidence — mentions entities
Patent — has_CPC, filed_by, covers

Documents are evidence, not the product.

⸻

6. Canonical Ontology Stack

Science:
	•	MeSH
	•	UniProt + HGNC
	•	ChEMBL + WHO INN
	•	OpenTargets
	•	ClinicalTrials.gov
	•	PubMed + Crossref

Business & IP:
	•	SEC EDGAR (CIK)
	•	LEI
	•	NAICS (via SIC → NAICS)
	•	CPC
	•	ORCID + PubMed authors

⸻

7. Company Identity

Public companies use CIK + LEI.
Private companies are discovered via trials, patents, publications, and deals and assigned stable slugs until they file or are acquired.

A company is real if it runs a trial, owns a drug, files a patent, or signs a deal.

⸻

8. Data Sources

Structured:
	•	MeSH
	•	ChEMBL
	•	OpenTargets
	•	ClinicalTrials

Live:
	•	PubMed
	•	Crossref
	•	SEC EDGAR
	•	FDA / EMA
	•	PR + RSS
	•	bioRxiv / medRxiv
	•	Patent feeds

⸻

9. Ingestion Gate

Only ingest content that touches existing entities.

New document → extract entities → match? → ingest + link → otherwise discard or shadow-promote.

⸻

10. Canonical IDs

Drug: ChEMBL
Target: UniProt
Disease: MeSH
Trial: NCT
Company: CIK + LEI
Publication: DOI or PMID
Patent: publication number + CPC

⸻

11. Architecture

Postgres is the system of record.
Neo4j is a projection for traversal and visualization.
Postgres FTS + pgvector handle search and embeddings.
LLM interprets intent and narrates results.
Reader fetches public content on demand or links out.

⸻

12. Embeddings

Used for:
	•	semantic entity search
	•	similarity
	•	evidence retrieval

Generated from names, abstracts, and short metadata.
Never used as truth.

⸻

13. AI Strategy

AI interprets intent, selects entities, runs graph queries, and summarizes with citations.
AI never invents facts.

⸻

14. Moat

The moat is a continuously updated, curated, entity-linked representation of life-sciences reality.

⸻

15. Legal

All sources allow metadata reuse and prohibit full-text redistribution.
We store IDs, abstracts, tags, and links — never paywalled content.

⸻

16. End State

This becomes the ledger of life-sciences reality:
who owns what, what works, what failed, who is moving, and why.
