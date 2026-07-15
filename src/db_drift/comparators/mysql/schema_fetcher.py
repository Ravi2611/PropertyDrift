from sqlalchemy import inspect
from .mysql_connection import get_mysql_engine
from src.db_drift.utils.logger import get_logger

logger = get_logger("MySQLFetcher")

class MySQLSchemaFetcher:
    def __init__(self, host, port, database, user=None, password=None):
        logger.info(f"Connecting to MySQL: {host}:{port}/{database}")
        self.engine = get_mysql_engine(host, port, database, user, password)
        self.inspector = inspect(self.engine)
        logger.debug("SQLAlchemy inspector initialized")

    def fetch_schema(self):
        logger.info("Fetching full database schema...")
        schema = {}
        tables = self.inspector.get_table_names()
        logger.debug(f"Found {len(tables)} tables to process")
        
        for table in tables:
            schema[table] = {
                "columns": self.fetch_columns(table),
                "indexes": self.fetch_indexes(table),
                "constraints": self.fetch_constraints(table)
            }
        return schema

    def fetch_columns(self, table):
        columns = {}
        for col in self.inspector.get_columns(table):
            columns[col['name']] = {
                "type": str(col['type']),
                "nullable": col['nullable'],
                "default": col['default'],
                "autoincrement": col.get('autoincrement', False)
            }
        return columns

    def fetch_indexes(self, table):
        indexes = {}
        for idx in self.inspector.get_indexes(table):
            indexes[idx['name']] = {
                "columns": idx['column_names'],
                "unique": idx['unique']
            }
        return indexes

    def fetch_constraints(self, table):
        constraints = {
            "primary_key": self.inspector.get_pk_constraint(table),
            "foreign_keys": self.inspector.get_foreign_keys(table),
            "unique_constraints": self.inspector.get_unique_constraints(table)
        }
        return constraints
