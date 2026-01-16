from backend.loaders.target_mesh import TARGET_MESH_IDS

def filter_to_target_mesh(df, col_candidates=("mesh_id", "mesh_ids", "mesh_terms")):
    for c in col_candidates:
        if c in df.columns:
            return df[df[c].apply(
                lambda v: any(m in TARGET_MESH_IDS for m in (v if isinstance(v, (list, set, tuple)) else [v]))
            )]
    return df
