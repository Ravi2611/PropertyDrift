from fastapi import APIRouter, HTTPException, Response
from .request_models import ScanRequest
from pathlib import Path
from src.db_drift.core.drift_engine import DriftEngine
from src.db_drift.core.csv_exporter import export_to_csv
from src.db_drift.utils.logger import get_logger

logger = get_logger("APIRoutes")

router = APIRouter()

@router.get("/health")
async def health_check():
    logger.debug("Health check requested")
    return {"status": "healthy", "engine": "ready"}

# Initialize engine — resolve config paths relative to this package, not CWD.
_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
ENV_PATH = str(_CONFIG_DIR / "environments.yaml")
IGNORE_PATH = str(_CONFIG_DIR / "ignore_rules.yaml")
engine = DriftEngine(ENV_PATH, IGNORE_PATH)

@router.get("/environments")
async def get_environments():
    logger.debug("Received request for environments list")
    envs = list(engine.env_config['environments'].keys())
    logger.info(f"Returning {len(envs)} environments")
    return envs

@router.get("/databases")
async def get_databases(env: str, db_type: str):
    logger.debug(f"Received request for databases in {env} of type {db_type}")
    if env not in engine.env_config['environments']:
        logger.warning(f"Environment {env} not found")
        return []
    dbs = [db['name'] for db in engine.env_config['environments'][env].get(db_type, [])]
    logger.info(f"Returning {len(dbs)} databases for {env}")
    return dbs

@router.post("/scan")
async def run_scan(request: ScanRequest):
    logger.info(f"Received SCAN request: {request.baseline_env} -> {request.target_env} (Type: {request.db_type}, Mock: {request.use_mock})")
    try:
        report = engine.run_scan(
            request.baseline_env,
            request.target_env,
            compare_mysql=(request.db_type == 'mysql'),
            compare_mongo=(request.db_type == 'mongo'),
            db_name=request.db_name,
            use_mock=request.use_mock
        )
        logger.info("Scan completed successfully, returning report")
        return report
    except Exception as e:
        logger.error(f"Scan failed with error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/export")
async def export_scan(request: ScanRequest):
    logger.info(f"Received EXPORT request: {request.baseline_env} -> {request.target_env}")
    try:
        report = engine.run_scan(
            request.baseline_env,
            request.target_env,
            compare_mysql=(request.db_type == 'mysql'),
            compare_mongo=(request.db_type == 'mongo'),
            db_name=request.db_name,
            use_mock=request.use_mock
        )
        csv_content = export_to_csv(report)
        filename = f"drift_report_{request.baseline_env}_to_{request.target_env}.csv"
        logger.info(f"Export generated successfully: {filename}")
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Export failed with error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
