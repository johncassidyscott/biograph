#!/usr/bin/env python3
"""Reset database - drop all tables and recreate schema"""

from dotenv import load_dotenv
load_dotenv()

from app.db import get_conn

def reset_database():
    """Drop all tables and recreate schema"""

    drop_sql = """
    -- Drop tables in reverse order of dependencies
    DROP TABLE IF EXISTS edge CASCADE;
    DROP TABLE IF EXISTS alias CASCADE;
    DROP TABLE IF EXISTS trial CASCADE;
    DROP TABLE IF EXISTS drug_approval CASCADE;
    DROP TABLE IF EXISTS mesh_alias CASCADE;
    DROP TABLE IF EXISTS mesh_tree CASCADE;
    DROP TABLE IF EXISTS mesh_descriptor CASCADE;
    DROP TABLE IF EXISTS entity CASCADE;
    """

    print("🗑️  Dropping all tables...")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(drop_sql)
        conn.commit()
    print("✓ All tables dropped")

    print("\n📋 Recreating schema...")
    with open("app/schema.sql", "r") as f:
        schema_sql = f.read()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
    print("✓ Schema recreated")

    print("\n✅ Database reset complete - ready for fresh build!")

if __name__ == "__main__":
    reset_database()
