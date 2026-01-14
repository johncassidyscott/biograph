#!/usr/bin/env python3
"""
Load MeSH Descriptors (descYYYY.xml.gz) into foundation tables, and promote Diseases into entity+alias.
- Foundation tables (complete): mesh_descriptor, mesh_tree, mesh_alias
- Promotion (scoped): entity(kind='disease') + alias rows for MeSH entry terms
"""
import gzip
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from typing import Iterable, List, Tuple
from app.db import get_conn

MESH_BASE = "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh"

def download(url: str, out_path: str) -> None:
   os.makedirs(os.path.dirname(out_path), exist_ok=True)
   if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
       return
   print(f"Downloading: {url}")
   with urllib.request.urlopen(url) as r, open(out_path, "wb") as f:
       while True:
           chunk = r.read(1024 * 1024)
           if not chunk:
               break
           f.write(chunk)
   print(f"Saved: {out_path} ({os.path.getsize(out_path)} bytes)")

def batched(it: Iterable[Tuple], n: int) -> Iterable[List[Tuple]]:
   batch: List[Tuple] = []
   for x in it:
       batch.append(x)
       if len(batch) >= n:
           yield batch
           batch = []
   if batch:
       yield batch

def iter_descriptor_records(xml_gz_path: str):
   # Stream parse to avoid loading huge XML into memory
   with gzip.open(xml_gz_path, "rb") as f:
       context = ET.iterparse(f, events=("end",))
       for event, elem in context:
           if elem.tag == "DescriptorRecord":
               yield elem
               elem.clear()

def get_text(elem, path: str) -> str | None:
   node = elem.find(path)
   if node is None or node.text is None:
       return None
   return node.text.strip()

def load_mesh(year: int, promote_diseases: bool = True, batch_size: int = 1000) -> None:
   desc_gz = f"desc{year}.gz"
   url = f"{MESH_BASE}/{desc_gz}"
   # Find repo root (go up from loaders/ to backend/ to repo/)
   repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
   raw_path = os.path.join(repo_root, "data", "raw", "mesh", desc_gz)
   download(url, raw_path)
   # Accumulators
   desc_rows = []   # (ui, name)
   tree_rows = []   # (ui, tree_number)
   alias_rows = []  # (ui, alias)
   # Promotion accumulators
   disease_entity_rows = []  # (kind, canonical_id, name)
   disease_alias_rows = []   # (canonical_id, alias, source)
   total = 0
   promoted = 0
   with get_conn() as conn:
       with conn.cursor() as cur:
           for rec in iter_descriptor_records(raw_path):
               total += 1
               ui = get_text(rec, "./DescriptorUI")
               name = get_text(rec, "./DescriptorName/String")
               if not ui or not name:
                   continue
               desc_rows.append((ui, name))
               # Tree numbers
               tree_nums = [t.text.strip() for t in rec.findall("./TreeNumberList/TreeNumber") if t.text]
               for tn in tree_nums:
                   tree_rows.append((ui, tn))
               # Entry terms: pull from all Concepts/Terms
               terms = []
               for term in rec.findall("./ConceptList/Concept/TermList/Term/String"):
                   if term.text:
                       s = term.text.strip()
                       if s and s != name:
                           terms.append(s)
               # De-dup per descriptor record
               seen = set()
               for s in terms:
                   if s.lower() in seen:
                       continue
                   seen.add(s.lower())
                   alias_rows.append((ui, s))
               # Promote diseases: any TreeNumber under 'C'
               is_disease = promote_diseases and any(tn.startswith("C") for tn in tree_nums)
               if is_disease:
                   promoted += 1
                   canonical_id = f"MESH:{ui}"
                   disease_entity_rows.append(("disease", canonical_id, name))
                   for s in seen:
                       # store original casing by re-finding (cheap approach: just use s from terms loop)
                       pass
                   # add aliases with original casing (use alias_rows last chunk for this ui)
                   for s in terms:
                       if s and s != name:
                           disease_alias_rows.append((canonical_id, s, "mesh"))
               # Flush batches
               if len(desc_rows) >= batch_size:
                   _flush(cur, desc_rows, tree_rows, alias_rows, disease_entity_rows, disease_alias_rows)
                   conn.commit()
                   desc_rows.clear(); tree_rows.clear(); alias_rows.clear()
                   disease_entity_rows.clear(); disease_alias_rows.clear()
                   if total % (batch_size * 5) == 0:
                       print(f"Processed {total} descriptor records...")
           # final flush
           _flush(cur, desc_rows, tree_rows, alias_rows, disease_entity_rows, disease_alias_rows)
       conn.commit()
   print(f"Done. Descriptor records processed: {total}")
   print(f"Diseases promoted (tree starts with C): {promoted}")

def _flush(cur, desc_rows, tree_rows, alias_rows, disease_entity_rows, disease_alias_rows) -> None:
   # Foundation tables
   if desc_rows:
       cur.executemany(
           """
           insert into mesh_descriptor (ui, name)
           values (%s, %s)
           on conflict (ui) do update set name = excluded.name
           """,
           desc_rows,
       )
   if tree_rows:
       cur.executemany(
           """
           insert into mesh_tree (ui, tree_number)
           values (%s, %s)
           on conflict (ui, tree_number) do nothing
           """,
           tree_rows,
       )
   if alias_rows:
       cur.executemany(
           """
           insert into mesh_alias (ui, alias)
           values (%s, %s)
           on conflict (ui, alias) do nothing
           """,
           alias_rows,
       )
   # Promotion tables
   if disease_entity_rows:
       cur.executemany(
           """
           insert into entity (kind, canonical_id, name)
           values (%s, %s, %s)
           on conflict (kind, canonical_id) do update
             set name = excluded.name,
                 updated_at = now()
           """,
           disease_entity_rows,
       )
   if disease_alias_rows:
       # Need entity_id for alias table, so do an insert-select
       # Canonical id is MESH:<UI> in entity
       cur.executemany(
           """
           insert into alias (entity_id, alias, source)
           select e.id, %s, %s
           from entity e
           where e.kind = 'disease' and e.canonical_id = %s
           on conflict do nothing
           """,
           [(a, src, cid) for (cid, a, src) in disease_alias_rows],
       )

if __name__ == "__main__":
   # Default to 2026 because your spec date is Jan 2026 and NLM lists 2026 files.  [oai_citation:1‡NLM Pubs](https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/?utm_source=chatgpt.com)
   year = 2026
   if len(sys.argv) > 1:
       year = int(sys.argv[1])
   load_mesh(year=year, promote_diseases=True, batch_size=1000)