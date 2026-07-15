def compare_constraints(baseline_cons, target_cons):
    drifts = []
    
    # Primary Key
    if baseline_cons.get('primary_key') != target_cons.get('primary_key'):
        drifts.append({
            "severity": "WARNING",
            "type": "CONSTRAINT_MISMATCH",
            "object": "PRIMARY KEY",
            "detail": f"Expected {baseline_cons.get('primary_key')}, found {target_cons.get('primary_key')}"
        })

    # Foreign Keys
    baseline_fks = {fk['name']: fk for fk in baseline_cons.get('foreign_keys', [])}
    target_fks = {fk['name']: fk for fk in target_cons.get('foreign_keys', [])}
    
    for fk_name, baseline_fk in baseline_fks.items():
        if fk_name not in target_fks:
            drifts.append({
                "severity": "WARNING",
                "type": "CONSTRAINT_MISMATCH",
                "object": fk_name,
                "detail": "Missing foreign key in target"
            })
        else:
            if baseline_fk != target_fks[fk_name]:
                drifts.append({
                    "severity": "WARNING",
                    "type": "CONSTRAINT_MISMATCH",
                    "object": fk_name,
                    "detail": "Foreign key definition mismatch"
                })

    for fk_name in target_fks:
        if fk_name not in baseline_fks:
            drifts.append({
                "severity": "INFO",
                "type": "CONSTRAINT_MISMATCH",
                "object": fk_name,
                "detail": "Extra foreign key in target"
            })

    # Unique Constraints
    baseline_ucs = {uc['name']: uc for uc in baseline_cons.get('unique_constraints', [])}
    target_ucs = {uc['name']: uc for uc in target_cons.get('unique_constraints', [])}
    
    for uc_name, baseline_uc in baseline_ucs.items():
        if uc_name not in target_ucs:
            drifts.append({
                "severity": "WARNING",
                "type": "CONSTRAINT_MISMATCH",
                "object": uc_name,
                "detail": "Missing unique constraint in target"
            })
        else:
            if baseline_uc != target_ucs[uc_name]:
                drifts.append({
                    "severity": "WARNING",
                    "type": "CONSTRAINT_MISMATCH",
                    "object": uc_name,
                    "detail": "Unique constraint definition mismatch"
                })

    for uc_name in target_ucs:
        if uc_name not in baseline_ucs:
            drifts.append({
                "severity": "INFO",
                "type": "CONSTRAINT_MISMATCH",
                "object": uc_name,
                "detail": "Extra unique constraint in target"
            })
            
    return drifts
