from .mongo_connection import get_mongo_client
from src.db_drift.utils.logger import get_logger

logger = get_logger("MongoComparator")

class MongoComparator:
    def __init__(self, baseline_config, target_config, ignore_matcher=None):
        logger.info(f"Initialized MongoComparator with {len(baseline_config)} baseline and {len(target_config)} target configs")
        self.baseline_config = baseline_config
        self.target_config = target_config
        self.ignore_matcher = ignore_matcher

    def compare(self):
        results = {}
        errors = []
        
        baseline_dbs = {db['name']: db for db in self.baseline_config}
        target_dbs = {db['name']: db for db in self.target_config}
        
        all_db_names = set(baseline_dbs.keys()) | set(target_dbs.keys())
        logger.debug(f"Databases to compare: {all_db_names}")
        
        for db_name in all_db_names:
            logger.info(f"Processing MongoDB database: {db_name}")
            results[db_name] = []
            
            if db_name in baseline_dbs and db_name not in target_dbs:
                logger.warning(f"Database {db_name} missing in target")
                results[db_name].append({
                    "severity": "CRITICAL",
                    "type": "MISSING_DATABASE",
                    "object": db_name,
                    "detail": "Missing in target environment"
                })
                continue
                
            if db_name not in baseline_dbs and db_name in target_dbs:
                logger.info(f"Database {db_name} present only in target")
                results[db_name].append({
                    "severity": "INFO",
                    "type": "EXTRA_DATABASE",
                    "object": db_name,
                    "detail": "Present only in target environment"
                })
                continue
            
            # Compare collections
            try:
                b_db = baseline_dbs[db_name]
                t_db = target_dbs[db_name]
                
                logger.debug(f"Connecting to MongoDB baseline: {b_db['replica_sets']}")
                b_client = get_mongo_client(
                    b_db['replica_sets'], 
                    database=b_db.get('database'),
                    user=b_db.get('user'), 
                    password=b_db.get('password')
                )
                logger.debug(f"Connecting to MongoDB target: {t_db['replica_sets']}")
                t_client = get_mongo_client(
                    t_db['replica_sets'], 
                    database=t_db.get('database'),
                    user=t_db.get('user'), 
                    password=t_db.get('password')
                )
                
                logger.info(f"Listing collections for {db_name}...")
                # b_collections = set(b_client[db_name].list_collection_names())
                # t_collections = set(t_client[db_name].list_collection_names())
                # Add this temporarily

                b_actual_db = b_db.get('database') or db_name
                t_actual_db = t_db.get('database') or db_name

                b_collections = set(b_client[b_actual_db].list_collection_names())
                t_collections = set(t_client[t_actual_db].list_collection_names())

                print(f"DEBUG >>> db_name={db_name}, b_actual_db={b_actual_db}, t_actual_db={t_actual_db}")

                logger.info(f"Found {len(b_collections)} baseline and {len(t_collections)} target collections")
                
                # Missing Collections
                for coll in b_collections:
                    if self.ignore_matcher and self.ignore_matcher.is_collection_ignored("mongo", coll):
                        logger.debug(f"Ignoring collection: {coll}")
                        continue
                    if coll not in t_collections:
                        logger.warning(f"Collection missing in target: {coll}")
                        results[db_name].append({
                            "severity": "CRITICAL",
                            "type": "MISSING_COLLECTION",
                            "object": coll,
                            "detail": "Missing in target"
                        })
                
                # Extra Collections
                for coll in t_collections:
                    if self.ignore_matcher and self.ignore_matcher.is_collection_ignored("mongo", coll):
                        continue
                    if coll not in b_collections:
                        logger.info(f"Extra collection in target: {coll}")
                        results[db_name].append({
                            "severity": "INFO",
                            "type": "EXTRA_COLLECTION",
                            "object": coll,
                            "detail": "Present only in target"
                        })
                
                # Compare Indexes for collections present in both
                common_collections = b_collections & t_collections
                logger.info(f"Comparing indexes for {len(common_collections)} shared collections")
                for coll in common_collections:
                    if self.ignore_matcher and self.ignore_matcher.is_collection_ignored("mongo", coll):
                        continue
                        
                    logger.debug(f"Fetching indexes for collection: {coll}")
                    # b_indexes = b_client[db_name][coll].index_information()
                    # t_indexes = t_client[db_name][coll].index_information()
                    b_indexes = b_client[b_actual_db][coll].index_information()
                    t_indexes = t_client[t_actual_db][coll].index_information()
                    # Check for missing indexes in target
                    for idx_name, idx_spec in b_indexes.items():
                        if idx_name not in t_indexes:
                            logger.warning(f"Index {idx_name} missing on {coll}")
                            results[db_name].append({
                                "severity": "WARNING",
                                "type": "MISSING_INDEX",
                                "object": f"{coll}.{idx_name}",
                                "detail": f"Index {idx_name} missing in target"
                            })
                        elif idx_spec != t_indexes[idx_name]:
                            logger.warning(f"Index definition mismatch on {coll}.{idx_name}")
                            results[db_name].append({
                                "severity": "CRITICAL",
                                "type": "INDEX_MISMATCH",
                                "object": f"{coll}.{idx_name}",
                                "detail": f"Index definition differs: {idx_spec} vs {t_indexes[idx_name]}"
                            })
                            
                    # Check for extra indexes in target
                    for idx_name in t_indexes:
                        if idx_name not in b_indexes:
                            logger.info(f"Extra index in target: {coll}.{idx_name}")
                            results[db_name].append({
                                "severity": "INFO",
                                "type": "EXTRA_INDEX",
                                "object": f"{coll}.{idx_name}",
                                "detail": f"Index {idx_name} present only in target"
                            })
                        
            except Exception as e:
                logger.error(f"Error comparing MongoDB database {db_name}: {str(e)}", exc_info=True)
                errors.append({
                    "component": "MONGO",
                    "database": db_name,
                    "detail": str(e)
                })
                
        return results, errors
