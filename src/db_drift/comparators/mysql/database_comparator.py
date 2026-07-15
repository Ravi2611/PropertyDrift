from .schema_fetcher import MySQLSchemaFetcher
from .table_comparator import compare_tables
from src.db_drift.utils.logger import get_logger

logger = get_logger("MySQLComparator")

class MySQLComparator:
    def __init__(self, baseline_config, target_config, ignore_matcher=None):
        logger.info(f"Initialized MySQLComparator with {len(baseline_config)} baseline and {len(target_config)} target DB configs")
        self.baseline_config = baseline_config
        self.target_config = target_config
        self.ignore_matcher = ignore_matcher

    def compare(self):
        results = {}
        errors = []
        
        baseline_dbs = {db['name']: db for db in self.baseline_config}
        target_dbs = {db['name']: db for db in self.target_config}
        
        all_db_names = set(baseline_dbs.keys()) | set(target_dbs.keys())
        logger.debug(f"Combined database list for comparison: {all_db_names}")
        
        for db_name in all_db_names:
            logger.info(f"Processing database: {db_name}")
            results[db_name] = []
            
            if db_name in baseline_dbs and db_name not in target_dbs:
                logger.warning(f"Database {db_name} is missing in target environment")
                results[db_name].append({
                    "severity": "CRITICAL",
                    "type": "MISSING_DATABASE",
                    "object": db_name,
                    "detail": "Missing in target environment"
                })
                continue
                
            if db_name not in baseline_dbs and db_name in target_dbs:
                logger.info(f"Database {db_name} is present only in target environment")
                results[db_name].append({
                    "severity": "INFO",
                    "type": "EXTRA_DATABASE",
                    "object": db_name,
                    "detail": "Present only in target environment"
                })
                continue
            
            # Both exist, compare schemas
            try:
                b_db = baseline_dbs[db_name]
                t_db = target_dbs[db_name]
                
                logger.debug(f"Initializing SchemaFetchers for {db_name}")
                # b_fetcher = MySQLSchemaFetcher(
                #     b_db['host'], b_db['port'], db_name, 
                #     user=b_db.get('user'), password=b_db.get('password')
                # )
                # t_fetcher = MySQLSchemaFetcher(
                #     t_db['host'], t_db['port'], db_name,
                #     user=t_db.get('user'), password=t_db.get('password')
                # )

                b_actual_db = b_db.get('database') or db_name
                t_actual_db = t_db.get('database') or db_name

                print(f"DEBUG >>> db_name={db_name}, b_actual_db={b_actual_db}, t_actual_db={t_actual_db}")

                b_fetcher = MySQLSchemaFetcher(
                    b_db['host'], b_db['port'], b_actual_db,  # ✅
                    user=b_db.get('user'), password=b_db.get('password')
                )
                t_fetcher = MySQLSchemaFetcher(
                    t_db['host'], t_db['port'], t_actual_db,  # ✅
                    user=t_db.get('user'), password=t_db.get('password')
                )
                
                logger.info(f"Fetching schemas for {db_name}...")
                b_schema = b_fetcher.fetch_schema()
                logger.debug(f"Baseline schema for {db_name} fetched ({len(b_schema)} tables)")
                t_schema = t_fetcher.fetch_schema()
                logger.debug(f"Target schema for {db_name} fetched ({len(t_schema)} tables)")
                
                logger.info(f"Running table-level comparison for {db_name}")
                db_drifts = compare_tables(b_schema, t_schema, self.ignore_matcher)
                logger.info(f"Comparison for {db_name} finished. Found {len(db_drifts)} drifts.")
                results[db_name].extend(db_drifts)
                
            except Exception as e:
                logger.error(f"Error comparing MySQL database {db_name}: {str(e)}", exc_info=True)
                errors.append({
                    "component": "MYSQL",
                    "database": db_name,
                    "detail": str(e)
                })
                
        return results, errors
