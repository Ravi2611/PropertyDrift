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
            return val_str.lower() in ('true', '1', 'yes', 't')
        if val_type == 'list' or val_type == 'dict':
            import json
            return json.loads(val_str.replace("'", "\""))
    except Exception as e:
        logger.warning(f"Failed to cast value '{val_str}' to {val_type}: {e}")
    
    return val_str

def sanitize_for_db(value):
    """Remove invalid UTF-8 characters that SQLite can't store."""
    if value is None:
        return None
    s = str(value)
    # Replace surrogate pairs and other invalid UTF-8
    return s.encode('utf-8', errors='replace').decode('utf-8', errors='replace')


def resolve_repo_path(repo_name: str) -> str:
    """`mock_repo` lives at the project root; every other repo lives under data/repos/."""
    return "mock_repo" if repo_name == "mock_repo" else os.path.join("data/repos", repo_name)


def _split_csv(value: Optional[str]) -> List[str]:
    """Parse a comma-separated query param into a clean list, dropping blanks/dupes (order-preserving)."""
    if not value:
        return []
    seen = set()
    out = []
    for item in value.split(","):
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out

app = FastAPI(
    title="DriftGuard API",
    root_path="/driftguard",
    description="""
## DriftGuard — Configuration Drift Detection & Remediation

DriftGuard scans Git-hosted configuration repositories to detect, report, and automatically fix **configuration drift** across environments (e.g. `s0` → `s1` → `uat`).

### What it does
- **Clones** GitLab/GitHub config repos and indexes their services and environments
- **Scans** for drift: missing keys, extra keys, value mismatches, and type mismatches between a baseline and target environment
- **Scores** each drift by severity (CRITICAL, WARNING, INFO)
- **Remediates** missing keys automatically, with optional GitLab Merge Request creation

### Key Concepts
| Term | Meaning |
|------|---------|
| **Service** | A folder inside the config repo representing one microservice |
| **Environment** | A subfolder like `s0`, `s1`, `uat` containing YAML/properties config files |
| **Baseline** | The reference environment to compare from (usually the stable one) |
| **Target** | The environment being checked for drift |
| **Drift Score** | Numeric score — higher means more critical drift |
| **Remediation** | Automatically inserting missing keys into target config files |

### Supported File Types
`.yml`, `.yaml`, `.properties`
    """,
    version="1.0.0",
)

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


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    tags=["System"],
    summary="Health Check",
    description="Returns `ok` if the API server is up and running. Used by infrastructure for liveness probes."
)
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

@app.post(
    "/repo/clone",
    tags=["Repository"],
    summary="Clone or Update a Repository",
    description="""
Clones a remote Git repository into the local `data/repos/` directory.
If the repo already exists locally, it fetches the latest changes instead of re-cloning.

**Returns:**
- `repo_name` — local folder name derived from the URL
- `branches` — all available remote branches
- `default_branch` — the HEAD branch (e.g. `master` or `main`)
- `services` — list of service directories found in the repo root
    """
)
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


@app.get(
    "/repo/{repo_name}/services",
    tags=["Repository"],
    summary="List Services in a Repository",
    description="""
Returns all service directories found inside a cloned repository.
Optionally checks out a specific branch before scanning.

A **service** is any top-level non-hidden folder inside the repo root (e.g. `post-order`, `payment-service`).
    """
)
def get_services(repo_name: str, branch: Optional[str] = None):
    logger.info(f"Request: GET /repo/{repo_name}/services | branch={branch}")
    repo_path = resolve_repo_path(repo_name)
    if not os.path.exists(repo_path):
        logger.warning(f"Repo not found: {repo_name}")
        raise HTTPException(status_code=404, detail="Repo not found")

    if repo_name != "mock_repo":
        if not branch:
            branch = git_manager.get_default_branch(repo_path)
        git_manager.checkout(repo_path, branch)

    scanner = RepoScanner()
    services = scanner.get_services(repo_path)
    return services


@app.get(
    "/repo/{repo_name}/envs",
    tags=["Repository"],
    summary="Browse Environments for a Service",
    description="""
Returns a navigable list of environment folders under a given service.
Supports hierarchical browsing via `sub_path` for repos that use nested structures like `service/stage/s0/`.

Each item in the response indicates:
- `name` — folder name (e.g. `s0`, `s1`, `uat`)
- `is_env` — `true` if the folder directly contains config files
- `is_folder` — `true` if the folder has sub-directories (drill down further)
    """
)
async def get_envs(repo_name: str, service: str, branch: str, sub_path: str = ""):
    repo_path = resolve_repo_path(repo_name)
    if not os.path.exists(repo_path):
        raise HTTPException(status_code=404, detail="Repo not found")

    if repo_name != "mock_repo":
        git_manager.checkout(repo_path, branch)
    return RepoScanner.get_environments(repo_path, service, sub_path)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

@app.get(
    "/scan",
    tags=["Scanning"],
    summary="Run a Drift Scan",
    description="""
Compares configuration files between a **baseline** and **target** environment for a given service,
and detects all drift — missing keys, extra keys, value mismatches, and type mismatches.

Each drift is assigned a **severity**:
| Severity | Meaning |
|----------|---------|
| `CRITICAL` | Key is present in baseline but completely missing in target |
| `WARNING` | Key exists but has an unexpected difference |
| `INFO` | Difference is expected (e.g. env-aware keys like URLs) |

Results are persisted to the database and returned with a `scan_id` for later retrieval and remediation.

> **Tip:** Use `baseline_branch` to compare across Git branches in addition to environment folders.

> **Multi-service:** Pass `services=svc1,svc2,svc3` to scan several services in one run
> (all sharing the same baseline/target env). The single `service` param is still
> supported for one-service scans.
    """
)
def run_scan(
    repo_name: str = "mock_repo",
    service: str = "service-A",
    baseline_env: str = "s0",
    target_env: str = "s1",
    baseline_branch: Optional[str] = None,
    services: Optional[str] = None,
):
    svc_list = _split_csv(services) or ([service] if service else [])
    logger.info(f"Request: GET /scan | repo={repo_name} | services={svc_list} | baseline={baseline_env} | target={target_env} | branch={baseline_branch}")

    if not svc_list:
        raise HTTPException(status_code=400, detail="No service(s) specified")

    repo_path = resolve_repo_path(repo_name)

    if not os.path.exists(repo_path):
        logger.warning(f"Scan failed: Repo not found: {repo_path}")
        raise HTTPException(status_code=404, detail="Repo not found")

    rule_manager = RuleManager("config/rules.yaml")
    drift_engine = DriftEngine(rule_manager)

    if baseline_branch:
        git_manager.checkout(repo_path, baseline_branch)

    all_diffs = []
    for svc in svc_list:
        all_diffs.extend(drift_engine.compare_environments(repo_path, svc, baseline_env, target_env))
    score = drift_engine.calculate_drift_score(all_diffs)

    services_csv = ",".join(svc_list)
    return _persist_scan(
        diffs=all_diffs,
        score=score,
        mode="single",
        repo_name=repo_name,
        baseline_repo=repo_name,
        target_repo=repo_name,
        baseline_service=services_csv,
        target_service=services_csv,
        baseline_env=baseline_env,
        target_env=target_env,
        baseline_branch=baseline_branch,
        target_branch=baseline_branch,
        total_services=len(svc_list),
    )


def _persist_scan(
    *,
    diffs,
    score: int,
    mode: str,
    repo_name: str,
    baseline_repo: str,
    target_repo: str,
    baseline_service: str,
    target_service: str,
    baseline_env: str,
    target_env: str,
    baseline_branch: Optional[str],
    target_branch: Optional[str],
    total_services: int = 1,
):
    """Shared persistence path for both single- and dual-repo scans.

    For multi-service scans, `baseline_service` / `target_service` are the
    comma-joined display strings for the whole run; exact per-drift attribution
    lives on each DriftRecord (`service` = target service, `baseline_service` =
    baseline service), which the engine tags per service.
    """
    with Session(engine) as session:
        history = ScanHistory(
            repo_name=repo_name,
            baseline_env=baseline_env,
            target_env=target_env,
            total_services=total_services,
            total_drifts=len(diffs),
            critical_drifts=sum(1 for d in diffs if d.severity == "CRITICAL"),
            mode=mode,
            baseline_repo=baseline_repo,
            target_repo=target_repo,
            baseline_branch=baseline_branch,
            target_branch=target_branch,
            baseline_service=baseline_service,
            target_service=target_service,
        )
        session.add(history)
        session.commit()
        session.refresh(history)

        all_diffs = []
        for d in diffs:
            record = DriftRecord(
                scan_id=history.id,
                service=d.service,  # engine sets this to the TARGET service in dual mode
                # Prefer the per-diff baseline service (correct for multi-service
                # scans); fall back to the scan-level value for older diffs.
                baseline_service=getattr(d, "baseline_service", None) or baseline_service,
                env=d.env,
                file=d.file,
                key=d.key,
                base_value=sanitize_for_db(d.base_value),
                target_value=sanitize_for_db(d.target_value),
                value_type=d.value_type,
                diff_type=d.diff_type,
                severity=d.severity,
                drift_score=score,
            )
            session.add(record)
            all_diffs.append(record)

        session.commit()
        drifts_list = []
        for d in all_diffs:
            session.refresh(d)
            drifts_list.append({
                "id": d.id,
                "timestamp": d.timestamp.isoformat() if d.timestamp else None,
                "service": d.service,
                "baseline_service": d.baseline_service,
                "env": d.env,
                "file": d.file,
                "key": d.key,
                "base_value": d.base_value,
                "target_value": d.target_value,
                "diff_type": d.diff_type,
                "severity": d.severity,
                "drift_score": d.drift_score,
            })
        scan_id = history.id

    logger.info(f"Success: scan | mode={mode} | scan_id={scan_id} | drifts_found={len(drifts_list)}")
    return {
        "status": "success",
        "scan_id": scan_id,
        "mode": mode,
        "drifts_found": len(drifts_list),
        "drifts": drifts_list,
    }


@app.get(
    "/scan/dual",
    tags=["Scanning"],
    summary="Run a Dual-Repo Drift Scan",
    description="""
Compares configuration files between **two different cloned repositories**.

Use this when the baseline and target live in **separate repos** (e.g. a shared
config repo vs a service-specific repo, or a legacy vs modern deployment).

You choose:
- `baseline_repo` + `baseline_service` + `baseline_env` (+ optional `baseline_branch`)
- `target_repo`   + `target_service`   + `target_env`   (+ optional `target_branch`)

Both repos must already be cloned via `POST /repo/clone`. Service folder names
can differ between the two repos — this endpoint does no auto-matching, it
compares exactly the two folders you point it at.

Remediation (via the standard `/remediate` and `/remediate/bulk` endpoints)
only ever writes to the **target** repo. The baseline repo is treated as
read-only.

**Multi-service:** Pass `baseline_services=a,b,c` and `target_services=x,y,z`
(index-aligned, same length) to compare several service pairs in one run. The
scalar `baseline_service`/`target_service` params are still supported for a
single pair.
    """,
)
def run_scan_dual(
    baseline_repo: str,
    target_repo: str,
    baseline_env: str,
    target_env: str,
    baseline_service: Optional[str] = None,
    target_service: Optional[str] = None,
    baseline_services: Optional[str] = None,
    target_services: Optional[str] = None,
    baseline_branch: Optional[str] = None,
    target_branch: Optional[str] = None,
):
    # Build the list of (baseline_service, target_service) pairs.
    base_list = _split_csv(baseline_services) or ([baseline_service] if baseline_service else [])
    tgt_list = _split_csv(target_services) or ([target_service] if target_service else [])

    if not base_list or not tgt_list:
        raise HTTPException(status_code=400, detail="No service pair(s) specified")
    if len(base_list) != len(tgt_list):
        raise HTTPException(
            status_code=400,
            detail=f"baseline_services ({len(base_list)}) and target_services ({len(tgt_list)}) must have the same length",
        )

    pairs = list(zip(base_list, tgt_list))
    logger.info(
        f"Request: GET /scan/dual | "
        f"baseline={baseline_repo}:{baseline_branch} | target={target_repo}:{target_branch} | pairs={pairs}"
    )

    baseline_repo_path = resolve_repo_path(baseline_repo)
    target_repo_path = resolve_repo_path(target_repo)

    if not os.path.exists(baseline_repo_path):
        raise HTTPException(status_code=404, detail=f"Baseline repo not found: {baseline_repo}")
    if not os.path.exists(target_repo_path):
        raise HTTPException(status_code=404, detail=f"Target repo not found: {target_repo}")

    # Check out the requested branch on each repo independently so we compare
    # exactly what the user asked for. Skipped for the mock_repo (no git).
    if baseline_branch and baseline_repo != "mock_repo":
        git_manager.checkout(baseline_repo_path, baseline_branch)
    if target_branch and target_repo != "mock_repo":
        git_manager.checkout(target_repo_path, target_branch)

    rule_manager = RuleManager("config/rules.yaml")
    drift_engine = DriftEngine(rule_manager)

    all_diffs = []
    for base_svc, tgt_svc in pairs:
        baseline_dir = DriftEngine.resolve_env_path(baseline_repo_path, base_svc, baseline_env)
        target_dir = DriftEngine.resolve_env_path(target_repo_path, tgt_svc, target_env)

        if not os.path.exists(baseline_dir):
            raise HTTPException(status_code=404, detail=f"Baseline env directory not found: {baseline_dir}")
        if not os.path.exists(target_dir):
            raise HTTPException(status_code=404, detail=f"Target env directory not found: {target_dir}")

        # `service_label` = target service (remediation writes there); env_label
        # = target env; baseline_service_label records the baseline side per pair.
        all_diffs.extend(drift_engine.compare_dirs(
            baseline_dir, target_dir,
            service_label=tgt_svc,
            env_label=target_env,
            baseline_service_label=base_svc,
        ))

    score = drift_engine.calculate_drift_score(all_diffs)

    baseline_services_csv = ",".join(base_list)
    target_services_csv = ",".join(tgt_list)
    return _persist_scan(
        diffs=all_diffs,
        score=score,
        mode="dual",
        # `repo_name` keeps pointing at the TARGET repo so any legacy consumer
        # (and the remediation path) resolves the correct write location.
        repo_name=target_repo,
        baseline_repo=baseline_repo,
        target_repo=target_repo,
        baseline_service=baseline_services_csv,
        target_service=target_services_csv,
        baseline_env=baseline_env,
        target_env=target_env,
        baseline_branch=baseline_branch,
        target_branch=target_branch,
        total_services=len(pairs),
    )


@app.get(
    "/results",
    tags=["Scanning"],
    summary="Query Drift Records",
    description="""
Fetches all stored drift records from the database, with optional filters.
Results are ordered by most recent first.

Use this to query historical drift across any service, environment, or severity level.
    """
)
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


@app.get(
    "/matrix",
    tags=["Scanning"],
    summary="Get Drift Score Matrix",
    description="""
Returns a nested `service → environment → score` matrix showing the latest drift score for each combination.

Useful for building a **heatmap dashboard** — higher scores mean more critical drift.

Optionally filter by `scan_id` to see the matrix for a specific scan run.
    """
)
def get_matrix(scan_id: Optional[int] = None):
    with Session(engine) as session:
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


@app.get(
    "/scans",
    tags=["Scanning"],
    summary="List Scan History",
    description="""
Returns a paginated list of past scan runs, ordered by most recent first.

Each entry includes the repo, environments compared, total drifts found, and count of critical drifts.
Use `limit` to control how many records are returned (default: 50).
    """
)
def get_scans(limit: int = 50):
    with Session(engine) as session:
        scans = session.exec(select(ScanHistory).order_by(ScanHistory.timestamp.desc()).limit(limit)).all()
    return scans


@app.get(
    "/scans/{scan_id}/drifts",
    tags=["Scanning"],
    summary="Get All Drifts for a Scan",
    description="""
Returns every drift record associated with a specific scan run identified by `scan_id`.

Use this after calling `/scan` to retrieve the full detailed breakdown of what drifted.
    """
)
def get_scan_drifts(scan_id: int):
    with Session(engine) as session:
        drifts = session.exec(select(DriftRecord).where(DriftRecord.scan_id == scan_id)).all()
    return drifts


# ---------------------------------------------------------------------------
# Remediation
# ---------------------------------------------------------------------------

@app.post(
    "/remediate",
    tags=["Remediation"],
    summary="Remediate a Single Drift",
    description="""
Automatically fixes a single **MISSING_KEY** drift record by inserting the missing configuration key
into the target environment's config file.

**How it works:**
1. Looks up the drift record by `record_id`
2. Applies any env-aware value transformations from `rules.yaml` (e.g. swapping `s0` URLs to `s1`)
3. Mirrors the key's style (quotes, formatting) from the baseline file
4. Creates a backup of the target file before writing
5. Injects the key into the correct position in the YAML/properties file

Set `create_mr=true` to automatically push the fix to a new Git branch and open a **GitLab Merge Request**.

> **Note:** Only `MISSING_KEY` drift types are supported for auto-remediation.
    """
)
def remediate(record_id: int, create_mr: bool = False, create_backup: bool = True):
    logger.info(f"Request: POST /remediate | record_id={record_id} | create_mr={create_mr} | create_backup={create_backup}")
    with Session(engine) as session:
        record = session.get(DriftRecord, record_id)
        if not record:
            logger.warning(f"Remediate failed: Record {record_id} not found")
            raise HTTPException(status_code=404, detail="Record not found")
        
        if record.diff_type != "MISSING_KEY":
            logger.warning(f"Remediate failed: Invalid diff_type {record.diff_type} for record {record_id}")
            raise HTTPException(status_code=400, detail="Only MISSING_KEY drifts can be remediated automatically")
        
        history = session.get(ScanHistory, record.scan_id)
        if not history:
            logger.error(f"Remediate failed: Scan history {record.scan_id} missing for record {record_id}")
            raise HTTPException(status_code=404, detail="Scan history not found")
        
        rule_manager = RuleManager("config/rules.yaml")
        final_value_str = rule_manager.transform_value(
            record.key, 
            record.base_value, 
            history.target_env, 
            history.baseline_env
        )
        
        final_value = cast_value(final_value_str, record.value_type)
        
        if final_value != record.base_value:
            logger.info(f"Remediate: Transformed value for {record.key} ({history.baseline_env} -> {history.target_env})")
            logger.debug(f"Remediate: Original='{record.base_value}' -> Transformed='{final_value}'")

        target_repo = history.target_repo or history.repo_name
        target_repo_path = resolve_repo_path(target_repo)
        # Per-record target service (correct for multi-service scans where
        # history.target_service is a comma-joined display string).
        target_service = record.service or history.target_service

        baseline_repo = history.baseline_repo or history.repo_name
        baseline_repo_path = resolve_repo_path(baseline_repo)
        baseline_service = record.baseline_service or record.service or history.baseline_service

        logger.debug(
            f"Remediate: mode={history.mode} | "
            f"target={target_repo}:{target_service}:{history.target_env} | "
            f"baseline={baseline_repo}:{baseline_service}:{history.baseline_env}"
        )

        target_env_path = DriftEngine.resolve_env_path(target_repo_path, target_service, history.target_env)
        target_file_path = os.path.join(target_env_path, record.file)
        logger.debug(f"Remediate: Final target file path resolved to {target_file_path}")

        if not os.path.exists(target_file_path):
            logger.error(f"Remediate failed: Target file not found at {target_file_path}")
            return {"status": "error", "detail": f"Target file not found at {target_file_path}"}

        baseline_env_path = DriftEngine.resolve_env_path(baseline_repo_path, baseline_service, history.baseline_env)
        baseline_file_path = os.path.join(baseline_env_path, record.file)

        remediator = ConfigRemediator()
        success = remediator.remediate_missing_key(
            target_file_path,
            record.key,
            final_value,
            baseline_file_path=baseline_file_path,
            repo_path=target_repo_path,
            git_manager=git_manager,
            create_backup=create_backup,
        )

        if not success:
            logger.error(f"Remediate failed: ConfigRemediator returned failure for {target_file_path}")
            raise HTTPException(status_code=500, detail="Remediation failed. Check logs.")

        msg = f"Remediated {record.key} in {target_repo}/{target_service}/{history.target_env}"
        if not create_backup:
            msg += " (no backup file)"
        if create_mr:
            try:
                branch = git_manager.push_with_mr(target_repo_path, [target_file_path], include_backups=create_backup)
                msg += f" | MR Created on branch: {branch}"
            except Exception as e:
                logger.error(f"MR Creation failed for individual fix: {e}")
                msg += " | WARNING: Git Push failed. See logs."

        logger.info(f"Success: POST /remediate | record_id={record_id} | path={target_file_path} | key={record.key}")
        return {"status": "success", "message": msg}


@app.post(
    "/remediate/bulk",
    tags=["Remediation"],
    summary="Bulk Remediate All Missing Keys in a Scan",
    description="""
Remediates **all MISSING_KEY drifts** found in a given scan run in a single operation.

Iterates through every missing key, applies env-aware value transformations, and injects them
into the respective target config files. A backup is created for each modified file.

Set `create_mr=true` to batch all fixes into a **single GitLab Merge Request** across all modified files.

**Response includes:**
- `total` — number of missing keys found
- `remediated` — number successfully fixed
- `results` — per-key success/failure breakdown
- `message` — summary + MR branch name if applicable

> **Tip:** Run `/scan` first to get a `scan_id`, then pass it here to fix everything at once.
    """
)
def remediate_bulk(scan_id: int, create_mr: bool = False, create_backup: bool = True):
    logger.info(f"Request: POST /remediate/bulk | scan_id={scan_id} | create_mr={create_mr} | create_backup={create_backup}")
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
        modified_files = set()

        target_repo = history.target_repo or history.repo_name
        target_repo_path = resolve_repo_path(target_repo)

        baseline_repo = history.baseline_repo or history.repo_name
        baseline_repo_path = resolve_repo_path(baseline_repo)
        baseline_service_hist = history.baseline_service

        for record in records:
            # Use per-record services. history.target_service / baseline_service
            # may be comma-joined display strings for multi-service scans, so we
            # rely on the exact per-drift attribution set by the engine.
            tgt_svc = record.service or history.target_service
            base_svc = record.baseline_service or record.service or baseline_service_hist

            target_env_path = DriftEngine.resolve_env_path(target_repo_path, tgt_svc, history.target_env)
            target_file_path = os.path.join(target_env_path, record.file)

            if not os.path.exists(target_file_path):
                logger.error(f"Bulk Remediate: Skipping {record.key} (file not found: {target_file_path})")
                results.append({"key": record.key, "success": False, "reason": "File not found"})
                continue

            final_value_str = rule_manager.transform_value(
                record.key,
                record.base_value,
                history.target_env,
                history.baseline_env,
            )
            final_value = cast_value(final_value_str, record.value_type)

            baseline_env_path = DriftEngine.resolve_env_path(baseline_repo_path, base_svc, history.baseline_env)
            baseline_file_path = os.path.join(baseline_env_path, record.file)

            success = remediator.remediate_missing_key(
                target_file_path,
                record.key,
                final_value,
                baseline_file_path=baseline_file_path,
                repo_path=target_repo_path,
                git_manager=git_manager,
                create_backup=create_backup,
            )
            results.append({"key": record.key, "success": success})
            if success:
                modified_files.add(target_file_path)

        success_count = sum(1 for r in results if r['success'])
        logger.info(f"Bulk Remediate Success: {success_count}/{len(records)} keys remediated")

        msg = f"{success_count}/{len(records)} keys remediated in {target_repo}."
        if not create_backup:
            msg += " (no backup files)"
        if create_mr and modified_files:
            try:
                branch = git_manager.push_with_mr(target_repo_path, list(modified_files), include_backups=create_backup)
                msg += f" MR Created on branch: {branch}"
            except Exception as e:
                logger.error(f"Bulk MR Creation failed: {e}")
                msg += " WARNING: Git Push failed."
                
        return {
            "status": "success", 
            "total": len(records), 
            "remediated": success_count,
            "message": msg,
            "results": results
        }
