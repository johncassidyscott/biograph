import pandas as pd
from pathlib import Path

TA_MAPPING_PATH = Path(__file__).resolve().parents[2] / "data" / "ta_mapping.csv"

def load_target_mesh():
    df = pd.read_csv(TA_MAPPING_PATH, dtype={"mesh_id": str})
    ids = set(df["mesh_id"].dropna().astype(str))
    return ids, df

TARGET_MESH_IDS, TA_MAPPING_DF = load_target_mesh()
