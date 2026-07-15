import fnmatch
import yaml
import os

class IgnoreMatcher:
    def __init__(self, config_path):
        self.rules = self._load_rules(config_path)

    def _load_rules(self, path):
        if not os.path.exists(path):
            return {"mysql": {"tables": [], "columns": []}, "mongo": {"collections": []}}
        with open(path, 'r') as f:
            return yaml.safe_load(f)

    def is_table_ignored(self, db_type, table_name):
        patterns = self.rules.get(db_type, {}).get("tables", [])
        return any(fnmatch.fnmatch(table_name, p) for p in patterns)

    def is_column_ignored(self, db_type, table_name, column_name):
        # Format can be "column_name" or "table_name.column_name"
        patterns = self.rules.get(db_type, {}).get("columns", [])
        full_name = f"{table_name}.{column_name}"
        
        for p in patterns:
            if fnmatch.fnmatch(column_name, p) or fnmatch.fnmatch(full_name, p):
                return True
        return False

    def is_collection_ignored(self, db_type, collection_name):
        patterns = self.rules.get(db_type, {}).get("collections", [])
        return any(fnmatch.fnmatch(collection_name, p) for p in patterns)
