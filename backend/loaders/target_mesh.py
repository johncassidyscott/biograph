"""Target MeSH IDs for filtering."""
import pandas as pd
import os

# Load TA mapping
TA_FILE = os.path.join(os.path.dirname(__file__), "../../data/ta_mapping.csv")
TA_MAPPING_DF = pd.read_csv(TA_FILE)

# Extract target MeSH IDs
TARGET_MESH_IDS = set(TA_MAPPING_DF["mesh_id"].unique())

print(f"Loaded {len(TARGET_MESH_IDS)} target MeSH IDs")
