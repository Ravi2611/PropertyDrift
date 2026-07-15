import yaml
import os
from src.db_drift.comparators.mysql.database_comparator import MySQLComparator
from src.db_drift.comparators.mongo.database_comparator import MongoComparator
from src.db_drift.core.ignore_matcher import IgnoreMatcher

from src.db_drift.core.report_builder import ReportBuilder

from src.db_drift.utils.logger import get_logger

logger = get_logger("DriftEngine")

class DriftEngine:
    def __init__(self, env_config_path, ignore_rules_path):
        logger.info(f"Initializing DriftEngine with config: {env_config_path}")
        self.env_config = self._load_config(env_config_path)
        logger.debug("Environment configuration loaded successfully")
        self.ignore_matcher = IgnoreMatcher(ignore_rules_path)
        logger.debug("Ignore rules matcher initialized")

    def _load_config(self, path):
        logger.debug(f"Opening config file and expanding variables: {path}")
        with open(path, 'r') as f:
            content = f.read()
            # Expand environment variables like ${DB_PASSWORD}
            expanded_content = os.path.expandvars(content)
            return yaml.safe_load(expanded_content)

    def run_scan(self, baseline_env, target_env, compare_mysql=True, compare_mongo=True, db_name=None, use_mock=False):
        logger.info(f"Starting scan: {baseline_env} -> {target_env} (Mock: {use_mock})")
        
        if use_mock:
            logger.info("Generating mock drift report...")
            return self._generate_mock_report(baseline_env, target_env, db_name)

        if baseline_env not in self.env_config['environments']:
            logger.error(f"Baseline env {baseline_env} not found")
            raise ValueError(f"Baseline environment {baseline_env} not found in config")
        if target_env not in self.env_config['environments']:
            logger.error(f"Target env {target_env} not found")
            raise ValueError(f"Target environment {target_env} not found in config")

        baseline = self.env_config['environments'][baseline_env]
        target = self.env_config['environments'][target_env]

        builder = ReportBuilder()
        logger.debug("ReportBuilder initialized")

        def filter_dbs(db_list):
            if not db_name:
                logger.debug(f"No specific database filter, using all {len(db_list)} DBs")
                return db_list
            filtered = [db for db in db_list if db['name'] == db_name]
            logger.debug(f"Filtered database list to: {[db['name'] for db in filtered]}")
            return filtered

        if compare_mysql:
            logger.info("Comparing MySQL schemas...")
            mysql_comp = MySQLComparator(
                filter_dbs(baseline.get('mysql', [])),
                filter_dbs(target.get('mysql', [])),
                self.ignore_matcher
            )
            mysql_results, mysql_errors = mysql_comp.compare()
            logger.info(f"MySQL comparison complete. Found drifts in {len(mysql_results)} databases.")
            builder.add_mysql_results(mysql_results)
            builder.add_errors(mysql_errors)

        if compare_mongo:
            logger.info("Comparing MongoDB schemas...")
            mongo_comp = MongoComparator(
                filter_dbs(baseline.get('mongo', [])),
                filter_dbs(target.get('mongo', [])),
                self.ignore_matcher
            )
            mongo_results, mongo_errors = mongo_comp.compare()
            logger.info(f"MongoDB comparison complete. Found drifts in {len(mongo_results)} databases.")
            builder.add_mongo_results(mongo_results)
            builder.add_errors(mongo_errors)

        logger.info("Finalizing drift report")
        return builder.build()

    def _generate_mock_report(self, baseline_env, target_env, db_name):
        logger.debug("Building mock report data structures")
        builder = ReportBuilder()
        
        mysql_mock = {
            "orders_db": [
                {"severity": "CRITICAL", "type": "MISSING_TABLE", "object": "invoices", "detail": "Table missing in target"},
                {"severity": "WARNING", "type": "DATATYPE_MISMATCH", "object": "users.name", "detail": "Expected VARCHAR(255), found TEXT"}
            ]
        }
        
        mongo_mock = {
            "gateway": [
                {"severity": "CRITICAL", "type": "MISSING_COLLECTION", "object": "sessions", "detail": "Missing in target"},
                {"severity": "CRITICAL", "type": "INDEX_MISMATCH", "object": "payments.tx_id_1", "detail": "Index uniqueness differs"}
            ]
        }
        
        builder.add_mysql_results(mysql_mock)
        builder.add_mongo_results(mongo_mock)
        logger.debug("Mock report generated successfully")
        return builder.build()
