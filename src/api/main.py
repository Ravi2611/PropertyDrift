from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select, func
from .models import DriftRecord, ScanHistory, engine, create_db_and_tables
from src.core.scanner import RepoScanner
from src.core.engine import DriftEngine
from src.core.rules import RuleManager
from src.core.git_manager import GitManager
from src.core.remediator import ConfigRemediator
from src.core.logger import setup_logger
import os
from typing import List, Dict, Optional, Any
import json

logger = setup_logger("API")

def cast_value(val_str: Optional[str], val_type: Optional[str]) -> Any:
    """Casts a string value back to its original Python type based on metadata."""
    if val_str is None:
        return None
    if not val_type or val_type == 'str':
        return val_str
    
    try:
        if val_type == 'int':
            return int(val_str)
        if val_type == 'float':
            return float(val_str)
        if val_type == 'bool':
            # Handle standard boolean strings
            return val_str.lower() in ('true', '1', 'yes', 't')
        if val_type == 'list' or val_type == 'dict':
            # For complex types, we might need json.loads, but for now primitives are priority
            import json
            return json.loads(val_str.replace("'", "\"")) # Basic attempt
    except Exception as e:
        logger.warning(f"Failed to cast value '{val_str}' to {val_type}: {e}")
    
    return val_str

app = FastAPI(title="DriftGuard API")
git_manager = GitManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

@app.post("/repo/clone")
def clone_repo(repo_url: str):
    logger.info(f"Request: POST /repo/clone | url={repo_url}")
    try:
        repo_path = git_manager.clone_or_update(repo_url)
        branches = git_manager.list_branches(repo_path)
        default_branch = git_manager.get_default_branch(repo_path)
        scanner = RepoScanner()
        services = scanner.get_services(repo_path)
        logger.info(f"Success: POST /repo/clone | repo={repo_url}")
        return {
            "status": "success",
            "repo_name": os.path.basename(repo_path),
            "branches": branches,
            "default_branch": default_branch,
            "services": services
        }
    except Exception as e:
        logger.error(f"Error: POST /repo/clone | url={repo_url} | error={str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/repo/{repo_name}/services")
def get_services(repo_name: str, branch: Optional[str] = None):
    logger.info(f"Request: GET /repo/{repo_name}/services | branch={branch}")
    repo_path = os.path.join("data/repos", repo_name)
    if not os.path.exists(repo_path):
        logger.warning(f"Repo not found: {repo_name}")
        raise HTTPException(status_code=404, detail="Repo not found")
    
    if not branch:
        branch = git_manager.get_default_branch(repo_path)
    
    git_manager.checkout(repo_path, branch)
    scanner = RepoScanner()
    services = scanner.get_services(repo_path)
    return services

@app.get("/repo/{repo_name}/envs")
async def get_envs(repo_name: str, service: str, branch: str, sub_path: str = ""):
    repo_path = os.path.join("data/repos", repo_name)
    if not os.path.exists(repo_path):
        raise HTTPException(status_code=404, detail="Repo not found")
    
    # Ensure branch is checked out
    git_manager.checkout(repo_path, branch)
    
    return RepoScanner.get_environments(repo_path, service, sub_path)

@app.get("/scan")
def run_scan(
    repo_name: str = "mock_repo",
    service: str = "service-A",
    baseline_env: str = "s0",
    target_env: str = "s1",
    baseline_branch: Optional[str] = None
):
    logger.info(f"Request: GET /scan | repo={repo_name} | service={service} | baseline={baseline_env} | target={target_env} | branch={baseline_branch}")
    repo_path = os.path.join("data/repos", repo_name) if repo_name != "mock_repo" else "mock_repo"
    
    if not os.path.exists(repo_path):
        logger.warning(f"Scan failed: Repo not found: {repo_path}")
        raise HTTPException(status_code=404, detail="Repo not found")
    
    rule_manager = RuleManager("config/rules.yaml")
    drift_engine = DriftEngine(rule_manager)
    
    # Simple case: same branch env comparison
    if baseline_branch:
        git_manager.checkout(repo_path, baseline_branch)
    
    diffs = drift_engine.compare_environments(repo_path, service, baseline_env, target_env)
    score = drift_engine.calculate_drift_score(diffs)
    
    with Session(engine) as session:
        history = ScanHistory(
            repo_name=repo_name,
            baseline_env=baseline_env,
            target_env=target_env,
            total_services=1,
            total_drifts=len(diffs),
            critical_drifts=sum(1 for d in diffs if d.severity == "CRITICAL")
        )
        session.add(history)
        session.commit()
        session.refresh(history)

        all_diffs = []
        for d in diffs:
            record = DriftRecord(
                scan_id=history.id,
                service=d.service,
                env=d.env,
                file=d.file,
                key=d.key,
                base_value=str(d.base_value) if d.base_value is not None else None,
                target_value=str(d.target_value) if d.target_value is not None else None,
                value_type=d.value_type,
                diff_type=d.diff_type,
                severity=d.severity,
                drift_score=score
            )
            session.add(record)
            all_diffs.append(record)
        
        session.commit()
        # Refresh and convert to dict explicitly to ensure all fields are captured
        drifts_list = []
        for d in all_diffs:
            session.refresh(d)
            drifts_list.append({
                "id": d.id,
                "timestamp": d.timestamp.isoformat() if d.timestamp else None,
                "service": d.service,
                "env": d.env,
                "file": d.file,
                "key": d.key,
                "base_value": d.base_value,
                "target_value": d.target_value,
                "diff_type": d.diff_type,
                "severity": d.severity,
                "drift_score": d.drift_score
            })
        scan_id = history.id
    
    logger.info(f"Success: GET /scan | scan_id={scan_id} | drifts_found={len(drifts_list)}")
    return {"status": "success", "scan_id": scan_id, "drifts_found": len(drifts_list), "drifts": drifts_list}

@app.get("/results")
def get_results(service: Optional[str] = None, env: Optional[str] = None, severity: Optional[str] = None):
    logger.info(f"Request: GET /results | service={service} | env={env} | severity={severity}")
    with Session(engine) as session:
        statement = select(DriftRecord)
        if service:
            statement = statement.where(DriftRecord.service == service)
        if env:
            statement = statement.where(DriftRecord.env == env)
        if severity:
            statement = statement.where(DriftRecord.severity == severity)
        
        results = session.exec(statement.order_by(DriftRecord.timestamp.desc())).all()
    return results

@app.get("/matrix")
def get_matrix(scan_id: Optional[int] = None):
    with Session(engine) as session:
        # Get latest score per service/env
        statement = select(DriftRecord)
        if scan_id:
            statement = statement.where(DriftRecord.scan_id == scan_id)
            
        results = session.exec(statement).all()
        matrix = {}
        for r in results:
            if r.service not in matrix:
                matrix[r.service] = {}
            if r.env not in matrix[r.service] or r.timestamp > matrix[r.service][r.env]['timestamp']:
                matrix[r.service][r.env] = {"score": r.drift_score, "timestamp": r.timestamp}
    return matrix

@app.get("/scans")
def get_scans(limit: int = 50):
    with Session(engine) as session:
        scans = session.exec(select(ScanHistory).order_by(ScanHistory.timestamp.desc()).limit(limit)).all()
    return scans

@app.get("/scans/{scan_id}/drifts")
def get_scan_drifts(scan_id: int):
    with Session(engine) as session:
        drifts = session.exec(select(DriftRecord).where(DriftRecord.scan_id == scan_id)).all()
    return drifts

@app.post("/remediate")
def remediate(record_id: int):
    logger.info(f"Request: POST /remediate | record_id={record_id}")
    with Session(engine) as session:
        record = session.get(DriftRecord, record_id)
        if not record:
            logger.warning(f"Remediate failed: Record {record_id} not found")
            raise HTTPException(status_code=404, detail="Record not found")
        
        if record.diff_type != "MISSING_KEY":
            logger.warning(f"Remediate failed: Invalid diff_type {record.diff_type} for record {record_id}")
            raise HTTPException(status_code=400, detail="Only MISSING_KEY drifts can be remediated automatically")
        
        # Get repo_name from history
        history = session.get(ScanHistory, record.scan_id)
        if not history:
            logger.error(f"Remediate failed: Scan history {record.scan_id} missing for record {record_id}")
            raise HTTPException(status_code=404, detail="Scan history not found")
        
        # Apply transformation logic if it's a MISSING_KEY
        rule_manager = RuleManager("config/rules.yaml")
        final_value_str = rule_manager.transform_value(
            record.key, 
            record.base_value, 
            history.target_env, 
            history.baseline_env
        )
        
        # Cast back to original type
        final_value = cast_value(final_value_str, record.value_type)
        
        if final_value != record.base_value:
            logger.info(f"Remediate: Transformed value for {record.key} ({history.baseline_env} -> {history.target_env})")
            logger.debug(f"Remediate: Original='{record.base_value}' -> Transformed='{final_value}'")

        repo_name = history.repo_name
        repo_path = os.path.join("data/repos", repo_name) if repo_name != "mock_repo" else "mock_repo"
        logger.debug(f"Remediate: Base repo path is {repo_path}")
        
        # Robust path resolution matching DriftEngine logic
        service_path = os.path.join(repo_path, record.service)
        logger.debug(f"Remediate: Checking service folder at {service_path}")
        
        env_path = os.path.join(service_path, "stage", record.env)
        logger.debug(f"Remediate: Probing for 'stage' structure at {env_path}")
        if not os.path.exists(env_path):
            logger.debug(f"Remediate: 'stage' structure not found. Falling back to {record.env} root.")
            env_path = os.path.join(service_path, record.env)
            
        target_file_path = os.path.join(env_path, record.file)
        logger.debug(f"Remediate: Final target file path resolved to {target_file_path}")
        
        if not os.path.exists(target_file_path):
            logger.error(f"Remediate failed: Target file not found at {target_file_path}")
            return {"status": "error", "detail": f"Target file not found at {target_file_path}"}

        # Resolve Baseline path for Mirror Styling
        baseline_env_path = os.path.join(service_path, "stage", history.baseline_env)
        if not os.path.exists(baseline_env_path):
            baseline_env_path = os.path.join(service_path, history.baseline_env)
        baseline_file_path = os.path.join(baseline_env_path, record.file)

        remediator = ConfigRemediator()
        success = remediator.remediate_missing_key(
            target_file_path, 
            record.key, 
            final_value,
            baseline_file_path=baseline_file_path,
            repo_path=repo_path,
            git_manager=git_manager
        )
        
        if not success:
            logger.error(f"Remediate failed: ConfigRemediator returned failure for {target_file_path}")
            raise HTTPException(status_code=500, detail="Remediation failed. Check logs.")
        
        logger.info(f"Success: POST /remediate | record_id={record_id} | path={target_file_path} | key={record.key}")
        return {"status": "success", "message": f"Remediated {record.key} in {record.service}/{record.env}"}

@app.post("/remediate/bulk")
def remediate_bulk(scan_id: int):
    logger.info(f"Request: POST /remediate/bulk | scan_id={scan_id}")
    with Session(engine) as session:
        history = session.get(ScanHistory, scan_id)
        if not history:
            raise HTTPException(status_code=404, detail="Scan history not found")
        
        statement = select(DriftRecord).where(
            DriftRecord.scan_id == scan_id,
            DriftRecord.diff_type == "MISSING_KEY"
        )
        records = session.exec(statement).all()
        
        if not records:
            return {"status": "success", "message": "No missing keys found to remediate"}
        
        logger.info(f"Bulk Remediate: Found {len(records)} missing keys for scan {scan_id}")
        
        remediator = ConfigRemediator()
        rule_manager = RuleManager("config/rules.yaml")
        results = []
        
        repo_path = os.path.join("data/repos", history.repo_name) if history.repo_name != "mock_repo" else "mock_repo"

        for record in records:
            # Resolve path
            service_path = os.path.join(repo_path, record.service)
            env_path = os.path.join(service_path, "stage", record.env)
            if not os.path.exists(env_path):
                env_path = os.path.join(service_path, record.env)
            target_file_path = os.path.join(env_path, record.file)
            
            if not os.path.exists(target_file_path):
                logger.error(f"Bulk Remediate: Skipping {record.key} (file not found: {target_file_path})")
                results.append({"key": record.key, "success": False, "reason": "File not found"})
                continue
            
            # Transform value
            final_value_str = rule_manager.transform_value(
                record.key, 
                record.base_value, 
                history.target_env, 
                history.baseline_env
            )
            
            # Cast back to original type
            final_value = cast_value(final_value_str, record.value_type)
            
            # Resolve Baseline path for Mirror Styling
            baseline_env_path = os.path.join(service_path, "stage", history.baseline_env)
            if not os.path.exists(baseline_env_path):
                baseline_env_path = os.path.join(service_path, history.baseline_env)
            baseline_file_path = os.path.join(baseline_env_path, record.file)

            # Apply fix
            success = remediator.remediate_missing_key(
                target_file_path, 
                record.key, 
                final_value,
                baseline_file_path=baseline_file_path,
                repo_path=repo_path,
                git_manager=git_manager
            )
            results.append({"key": record.key, "success": success})
            
        success_count = sum(1 for r in results if r['success'])
        logger.info(f"Bulk Remediate Success: {success_count}/{len(records)} keys remediated")
        
        return {
            "status": "success", 
            "total": len(records), 
            "remediated": success_count,
            "results": results
        }
