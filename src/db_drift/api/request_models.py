from pydantic import BaseModel
from typing import Optional

class ScanRequest(BaseModel):
    db_type: str # 'mysql' or 'mongo'
    baseline_env: str
    target_env: str
    db_name: Optional[str] = None # Optional: if None, compare all DBs of that type
    use_mock: Optional[bool] = False
