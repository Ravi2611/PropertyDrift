from typing import Optional, List
from sqlmodel import Field, SQLModel, create_engine, Session, select
from datetime import datetime

class DriftRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    scan_id: Optional[int] = Field(default=None, foreign_key="scanhistory.id")
    service: str
    env: str
    file: str
    key: str
    base_value: Optional[str]
    target_value: Optional[str]
    value_type: Optional[str]
    diff_type: str
    severity: str
    drift_score: int

class ScanHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    repo_name: str
    baseline_env: str
    target_env: str
    total_services: int
    total_drifts: int
    critical_drifts: int

sqlite_file_name = "data/driftguard.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
