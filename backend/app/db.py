import os
from contextlib import contextmanager
from typing import Iterator
from psycopg import Connection
from psycopg.rows import dict_row

def get_database_url() -> str:
   url = os.getenv("DATABASE_URL")
   if not url:
       raise RuntimeError("DATABASE_URL is not set (Codespaces secret).")
   return url

@contextmanager
def get_conn() -> Iterator[Connection]:
   conn: Connection = Connection.connect(get_database_url(), row_factory=dict_row)
   try:
       yield conn
   finally:
       conn.close()

def init_db(schema_path: str) -> None:
   with open(schema_path, "r", encoding="utf-8") as f:
       ddl = f.read()
   with get_conn() as conn:
       with conn.cursor() as cur:
           cur.execute(ddl)
       conn.commit()