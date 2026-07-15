from src.db_drift.utils.logger import get_logger

logger = get_logger("ColumnComparator")

def compare_columns(baseline_cols, target_cols):
    logger.debug(f"Comparing {len(baseline_cols)} baseline columns against {len(target_cols)} target columns")
    drifts = []
    
    # Missing Columns
    for col_name, baseline_meta in baseline_cols.items():
        if col_name not in target_cols:
            logger.warning(f"Column missing in target: {col_name}")
            drifts.append({
                "severity": "CRITICAL",
                "type": "MISSING_COLUMN",
                "object": col_name,
                "detail": "Missing in target"
            })
        else:
            target_meta = target_cols[col_name]
            # Datatype mismatch
            if baseline_meta['type'] != target_meta['type']:
                logger.info(f"Datatype mismatch on {col_name}")
                drifts.append({
                    "severity": "WARNING",
                    "type": "DATATYPE_MISMATCH",
                    "object": col_name,
                    "detail": f"Expected {baseline_meta['type']}, found {target_meta['type']}"
                })
            # Nullable mismatch
            if baseline_meta.get('nullable') != target_meta.get('nullable'):
                drifts.append({
                    "severity": "WARNING",
                    "type": "NULLABLE_MISMATCH",
                    "object": col_name,
                    "detail": f"Expected nullable={baseline_meta.get('nullable')}, found {target_meta.get('nullable')}"
                })
            # Default value mismatch
            if baseline_meta.get('default') != target_meta.get('default'):
                drifts.append({
                    "severity": "INFO",
                    "type": "DEFAULT_VALUE_MISMATCH",
                    "object": col_name,
                    "detail": f"Expected default={baseline_meta.get('default')}, found {target_meta.get('default')}"
                })
            # Auto-increment mismatch
            if baseline_meta.get('autoincrement', False) != target_meta.get('autoincrement', False):
                drifts.append({
                    "severity": "WARNING",
                    "type": "AUTO_INCREMENT_MISMATCH",
                    "object": col_name,
                    "detail": f"Expected autoincrement={baseline_meta.get('autoincrement', False)}, found {target_meta.get('autoincrement', False)}"
                })

    # Extra Columns
    for col_name in target_cols:
        if col_name not in baseline_cols:
            logger.info(f"Extra column in target: {col_name}")
            drifts.append({
                "severity": "INFO",
                "type": "EXTRA_COLUMN",
                "object": col_name,
                "detail": "Present only in target"
            })
            
    return drifts
