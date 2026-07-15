from .column_comparator import compare_columns
from .index_comparator import compare_indexes
from .constraint_comparator import compare_constraints
from src.db_drift.utils.logger import get_logger

logger = get_logger("TableComparator")

def compare_tables(baseline_schema, target_schema, ignore_matcher=None):
    logger.info(f"Starting table comparison: {len(baseline_schema)} baseline vs {len(target_schema)} target tables")
    drifts = []
    
    # Missing Tables
    for table_name, baseline_meta in baseline_schema.items():
        if ignore_matcher and ignore_matcher.is_table_ignored("mysql", table_name):
            logger.debug(f"Ignoring table: {table_name}")
            continue
            
        if table_name not in target_schema:
            logger.warning(f"Table missing in target: {table_name}")
            drifts.append({
                "severity": "CRITICAL",
                "type": "MISSING_TABLE",
                "object": table_name,
                "detail": "Missing in target"
            })
        else:
            target_meta = target_schema[table_name]
            logger.debug(f"Comparing table structure: {table_name}")
            
            # Compare Columns
            table_drifts = compare_columns(baseline_meta['columns'], target_meta['columns'])
            # Filter ignored columns
            if ignore_matcher:
                table_drifts = [d for d in table_drifts if not ignore_matcher.is_column_ignored("mysql", table_name, d['object'])]
            
            for d in table_drifts:
                d['database_object'] = table_name 
                drifts.append(d)
                
            # Compare Indexes
            index_drifts = compare_indexes(baseline_meta['indexes'], target_meta['indexes'])
            for d in index_drifts:
                d['database_object'] = table_name
                drifts.append(d)
                
            # Compare Constraints
            constraint_drifts = compare_constraints(baseline_meta['constraints'], target_meta['constraints'])
            for d in constraint_drifts:
                d['database_object'] = table_name
                drifts.append(d)
                
    # Extra Tables
    for table_name in target_schema:
        if ignore_matcher and ignore_matcher.is_table_ignored("mysql", table_name):
            continue
            
        if table_name not in baseline_schema:
            logger.info(f"Extra table in target: {table_name}")
            drifts.append({
                "severity": "INFO",
                "type": "EXTRA_TABLE",
                "object": table_name,
                "detail": "Present only in target"
            })
            
    return drifts
