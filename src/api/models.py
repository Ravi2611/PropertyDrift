from typing import Optional, List
from sqlmodel import Field, SQLModel, create_engine, Session, select
from sqlalchemy import text
from datetime import datetime

class DriftRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    scan_id: Optional[int] = Field(default=None, foreign_key="scanhistory.id")
    # In single-repo mode: `service` == baseline_service == target_service.
    # In dual-repo mode: `service` is the TARGET service folder (used for the
    # target file path during remediation). `baseline_service` is stored
    # separately for display / style mirroring.
    service: str
    baseline_service: Optional[str] = None
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
    # `repo_name` is preserved for backward compatibility. In single-repo mode
    # it is the only repo. In dual-repo mode it mirrors `target_repo` because
    # remediation (and any legacy caller) writes to the target.
    repo_name: str
    baseline_env: str
    target_env: str
    total_services: int
    total_drifts: int
    critical_drifts: int

    # Fields added for two-repo comparison. All are optional so existing rows
    # (and existing single-repo callers) stay valid.
    mode: Optional[str] = Field(default="single")  # "single" | "dual"
    baseline_repo: Optional[str] = None
    target_repo: Optional[str] = None
    baseline_branch: Optional[str] = None
    target_branch: Optional[str] = None
    baseline_service: Optional[str] = None
    target_service: Optional[str] = None

sqlite_file_name = "data/driftguard.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

engine = create_engine(sqlite_url, echo=False)


def _sqlite_migrate(conn, table: str, columns: dict):
    """Add any missing columns to an existing SQLite table.

    `columns` maps column name -> SQL type (e.g. {"mode": "VARCHAR"}).
    Safe to run on every startup; it is a no-op once columns exist.
    """
    existing = {
        row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    }
    for col_name, col_type in columns.items():
        if col_name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

    # Backfill new columns on pre-existing databases. SQLModel.create_all only
    # runs CREATE TABLE IF NOT EXISTS, so it never adds columns to a table that
    # already exists — we handle that manually here.
    with engine.begin() as conn:
        _sqlite_migrate(conn, "scanhistory", {
            "mode": "VARCHAR",
            "baseline_repo": "VARCHAR",
            "target_repo": "VARCHAR",
            "baseline_branch": "VARCHAR",
            "target_branch": "VARCHAR",
            "baseline_service": "VARCHAR",
            "target_service": "VARCHAR",
        })
        _sqlite_migrate(conn, "driftrecord", {
            "baseline_service": "VARCHAR",
        })
