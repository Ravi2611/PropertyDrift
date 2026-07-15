def compare_indexes(baseline_idxs, target_idxs):
    drifts = []
    
    for idx_name, baseline_meta in baseline_idxs.items():
        if idx_name not in target_idxs:
            drifts.append({
                "severity": "WARNING",
                "type": "INDEX_MISMATCH",
                "object": idx_name,
                "detail": "Missing index in target"
            })
        else:
            target_meta = target_idxs[idx_name]
            if baseline_meta.get('columns') != target_meta.get('columns') or \
               baseline_meta.get('unique') != target_meta.get('unique'):
                drifts.append({
                    "severity": "WARNING",
                    "type": "INDEX_MISMATCH",
                    "object": idx_name,
                    "detail": "Index definition mismatch (columns or uniqueness)"
                })

    for idx_name in target_idxs:
        if idx_name not in baseline_idxs:
            drifts.append({
                "severity": "INFO",
                "type": "EXTRA_INDEX",
                "object": idx_name,
                "detail": "Present only in target"
            })
            
    return drifts
