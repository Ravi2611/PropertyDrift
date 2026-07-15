# Mapping of drift types to their default severity levels
# As per requirements

DRIFT_SEVERITY = {
    "MISSING_DATABASE": "CRITICAL",
    "MISSING_TABLE": "CRITICAL",
    "MISSING_COLUMN": "CRITICAL",
    "MISSING_COLLECTION": "CRITICAL",
    
    "DATATYPE_MISMATCH": "WARNING",
    "NULLABLE_MISMATCH": "WARNING",
    "CONSTRAINT_MISMATCH": "WARNING",
    "INDEX_MISMATCH": "WARNING",
    "AUTO_INCREMENT_MISMATCH": "WARNING",
    
    "EXTRA_DATABASE": "INFO",
    "EXTRA_TABLE": "INFO",
    "EXTRA_COLUMN": "INFO",
    "EXTRA_COLLECTION": "INFO",
    "DEFAULT_VALUE_MISMATCH": "INFO",
    "EXTRA_INDEX": "INFO"
}

def get_severity(drift_type):
    return DRIFT_SEVERITY.get(drift_type, "INFO")
