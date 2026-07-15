# DriftGuard — Session Context / Handoff

> Paste this file (or its path) into a new chat to give it full context on the project
> and everything that was built/changed in the previous session.

---

## 0. Unified UI (latest change)

DriftGuard now bundles **two** drift tools behind a single FastAPI process on port `8051`:

| Surface | Route | Backend |
|---------|-------|---------|
| Launcher | `/` (`src/ui/home.html`) | Root `FastAPI` in `server.py` |
| Property Drift UI + API | `/property/…` | `src/api/main.py` (mounted sub-app), UI at `src/ui/property/` |
| DB Drift UI + API | `/db/…`, `/db/api/…` | `src/db_drift/app.py` (mounted sub-app) |

- `server.py` loads `.env`, mounts both sub-apps, exposes launcher at `/`.
- Property UI + History use a fetch prefix shim so existing `fetch('/scan')` etc. still work under `/property`. Same idea for DB UI under `/db`.
- Old `root_path="/driftguard"` on the Property FastAPI was removed (would collide with the new mount).
- DB Drift config paths in `src/db_drift/api/routes.py` are now resolved via `pathlib` relative to the package (no CWD assumption).
- New `.env` fallbacks: `MYSQL_USER`, `MYSQL_PASSWORD`, `MONGO_USER`, `MONGO_PASSWORD`.
- Deps added to `requirements.txt`: `sqlalchemy`, `pymysql`, `pymongo`, `jinja2`, `pandas`, `cryptography`.
- Legacy sibling folder `DBDrift/` (nested in this repo) has been removed after the merge; do not re-introduce it.

---

## 1. What this project is

**DriftGuard** (folder name `PropertyDrift`, branded "DriftGuard" in code/UI) detects
**configuration drift** between environments of Git-hosted config repos, reports it,
and can auto-remediate missing keys — optionally opening a GitLab Merge Request.

- **Backend:** FastAPI (Python 3.9), served by `server.py` via uvicorn on port **8051**.
- **DB:** SQLite (`data/driftguard.db`) via SQLModel.
- **Frontend:** static HTML/JS in `src/ui/` (`index.html` dashboard, `history.html`), served at `/`.
- **Config:** `config/rules.yaml` (ignore lists, severity overrides, env-aware value transforms).

### Run it

```bash
cd /Users/raviraj/Desktop/PropertyDrift
venv/bin/python server.py
# → http://localhost:8051/
```

If the port is stuck:

```bash
lsof -i :8051 -t | xargs kill -9 && venv/bin/python server.py
```

GitLab MR creation needs a `.env` with `GIT_USERNAME`, `GIT_TOKEN`, `GIT_DOMAIN`.

---

## 2. Architecture / key files

| File | Role |
|------|------|
| `server.py` | Entry point — loads `.env`, mounts UI, runs uvicorn on 8051 |
| `src/api/main.py` | All FastAPI endpoints, remediation orchestration, persistence |
| `src/api/models.py` | SQLModel tables `ScanHistory` + `DriftRecord`, DB creation + migration |
| `src/core/engine.py` | `DriftEngine` — compares two env directories, produces `DriftDiff`s |
| `src/core/scanner.py` | `RepoScanner` — lists services + browses env folders |
| `src/core/parser.py` | YAML/`.properties` parsers, flattens nested keys to dot-notation |
| `src/core/remediator.py` | `ConfigRemediator` — inserts missing keys, backups, style mirroring |
| `src/core/git_manager.py` | `GitManager` — clone/checkout/branch, `push_with_mr` |
| `src/core/rules.py` | `RuleManager` — ignore/severity/normalize/`transform_value` |
| `src/ui/index.html` | Dashboard: clone, pick services/envs, scan, remediate |
| `src/ui/history.html` | Past scans list + drill-down |
| `config/rules.yaml` | Runtime rules (NOT deployment config) |

### Cloned repos on disk

- `data/repos/<repo-name>/` — every cloned repo.
- `mock_repo/` (project root) — a special-cased fixture repo (no git) used for testing.
  In code, `resolve_repo_path("mock_repo")` returns `"mock_repo"`, everything else → `data/repos/<name>`.
- Current real clones present: `data/repos/stage-cloud-config`, `data/repos/prod-cloud-config`, `data/repos/mock-repo`.

### Repo folder convention

Services are top-level folders. Env folders live under either `{service}/stage/{env}/`
or `{service}/{env}/` — resolved by `DriftEngine.resolve_env_path()` (prefers the `stage/` form).
Env names can be nested/tiered (e.g. `uat/hongs-uat`), handled by the tiered UI pickers.

### Drift types & severity

`MISSING_KEY`, `EXTRA_KEY`, `VALUE_MISMATCH`, `TYPE_MISMATCH`, `MISSING_FILE`, `EXTRA_FILE`.
Severity: `CRITICAL` (10 pts), `WARNING` (2), `INFO` (0). **Only `MISSING_KEY` is auto-remediable.**

---

## 3. Features built in the previous session (in order)

### 3a. Two-repo (dual) comparison mode
Previously only single-repo (two envs in one repo). Added the ability to compare the
**same-purpose service across two different repos** (baseline repo A vs target repo B).

- **Decisions locked with the user:**
  - Service folder names may differ across repos; user picks them explicitly (no auto-matching).
  - Each repo can be on a different branch (`main`/`master`/`release`).
  - Baseline and target env names can differ, picked independently.
  - Remediation writes **only to the target repo (B)**; baseline (A) is never modified. MR goes to B.
  - Only missing keys auto-fixed. No repo-name collision handling needed.
- **DB:** `ScanHistory` gained `mode` (`"single"`/`"dual"`), `baseline_repo`, `target_repo`,
  `baseline_branch`, `target_branch`, `baseline_service`, `target_service`. `DriftRecord` gained
  `baseline_service`. All nullable + a lightweight `ALTER TABLE` migration in
  `create_db_and_tables()` (via `_sqlite_migrate`) so existing DBs upgrade in place.
- **Engine:** `compare_environments` refactored on top of a new public
  `compare_dirs(base_dir, target_dir, service_label, env_label, baseline_service_label)`.
  Also public static `resolve_env_path()`.
- **API:** new `GET /scan/dual`. `_persist_scan(...)` shared by both scan endpoints.
- **UI:** Single/Two-Repos mode toggle; dual panel with two clone/branch/env sections.
- **History:** shows mode + both repos/branches/services.

### 3b. "Create backup files" toggle
User wanted the option to skip `_backup` file creation during remediation.

- `ConfigRemediator.remediate_missing_key(..., create_backup: bool = True)` — when False,
  no `_backup` is written/rotated (existing backups left untouched).
- `GitManager.push_with_mr(..., include_backups: bool = True)` — when False, sibling
  `*_backup*` files are not staged into the commit nor restored to master after push.
- `POST /remediate` and `POST /remediate/bulk` both accept `create_backup: bool = True`.
- **UI:** a "Create backup files (recommended)" checkbox appears next to the Fix All buttons
  after a scan; both single-row and bulk fix actions read it.

### 3c. Multi-service scans (single + dual)
Scan several services in ONE run (one `scan_id`), sharing the same env pair.

- **Single:** `GET /scan?services=svc1,svc2,svc3` (loops `compare_environments` per service).
  Scalar `service` still works.
- **Dual:** `GET /scan/dual?baseline_services=a,b&target_services=x,y` (index-aligned pairs,
  must be equal length; iterates `compare_dirs` per pair). Scalars still work.
- `_split_csv()` helper parses the CSV params.
- `ScanHistory.baseline_service`/`target_service` store the **comma-joined display string**;
  exact per-drift attribution lives on each `DriftRecord` (`service` = target service,
  `baseline_service` = baseline service, tagged by the engine per service/pair).
- `_persist_scan` takes `total_services`.
- **Remediation uses per-record services** (`record.service` / `record.baseline_service`),
  NOT the comma-joined history fields — important so multi-service fixes hit the right folder.
- **UI single:** service dropdown → checkbox multi-picker (Select all / Clear, "(N selected)").
  Env browsing uses the first selected service (envs shared across services).
- **UI dual:** per-side service dropdowns removed; added a **Service Pairs builder**
  (rows of baseline↔target selects, + Add pair / remove). Appears once both repos cloned.
- **UI details table:** added a Service filter dropdown next to Type/Severity.
- **History:** truncates long service lists with tooltip + shows "N services" badge.

### 3d. Bug fix — remediation crash on null parent keys
**Symptom:** bulk fix reported e.g. `199/201`; one key like
`agg-adapter / s1 / default-tenant.yml : zoop.menu.pushUrl` was not remediated.

**Root cause:** In the target file the parent key `zoop.menu:` exists but is **null**
(all its children are commented out → YAML parses it as `None`). The old
`_remediate_yaml` navigation only created a parent map when the key was *absent*; it
descended into `None` and crashed with `'NoneType' object does not support item assignment`.
(Same error also recurred for `nxg-oms/.../application.yml` in the logs.)

**Fix (`src/core/remediator.py` `_remediate_yaml`):** for each parent path segment now:
- absent → create empty map (as before)
- **exists but null → promote to empty map, then nest** (the fix)
- exists as scalar/list → log clear error + return False (no data destruction, no crash)

Added `from collections.abc import Mapping` import for the type check.

---

## 4. Current API surface (relevant endpoints)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/repo/clone?repo_url=` | Clone/update, returns repo_name, branches, default_branch, services |
| GET | `/repo/{repo_name}/services?branch=` | List service folders |
| GET | `/repo/{repo_name}/envs?service=&branch=&sub_path=` | Tiered env browse |
| GET | `/scan` | Single-repo. Params: `repo_name, service, services(csv), baseline_env, target_env, baseline_branch` |
| GET | `/scan/dual` | Dual-repo. Params: `baseline_repo, target_repo, baseline_service(s), target_service(s), baseline_env, target_env, baseline_branch, target_branch` |
| GET | `/results`, `/matrix`, `/scans`, `/scans/{id}/drifts` | Query drift/history |
| POST | `/remediate?record_id=&create_mr=&create_backup=` | Fix one MISSING_KEY |
| POST | `/remediate/bulk?scan_id=&create_mr=&create_backup=` | Fix all MISSING_KEY in a scan |

FastAPI `root_path="/driftguard"` (docs/proxy prefix); UI fetches use bare paths (works when served by `server.py`).

---

## 5. Conventions / gotchas for the next session

- **Don't overwrite the real `README.md`** — it's the user-facing project doc (already updated
  with dual-repo, backup toggle, and multi-service sections).
- **Do NOT start the server yourself in the background** — the user runs it in their own
  terminal. A prior background instance caused an "address already in use" (port 8051) clash.
- **Smoke testing:** `httpx` is NOT installed, so `fastapi.testclient` fails. Instead, import
  the endpoint functions directly from `src.api.main` and call them (they return plain dicts).
  Always run against `mock_repo`, snapshot/restore any files you touch, and delete temp scripts.
- **mock_repo fixtures:** an earlier smoke `restore()` accidentally deleted pre-existing
  `_backup` fixture files; had to `git checkout --` them. When cleaning `_backup*` in tests,
  only remove ones the test created.
- **Per-record vs history service fields:** for multi-service scans, `ScanHistory.*_service`
  are comma-joined display strings. Always use `DriftRecord.service` /
  `DriftRecord.baseline_service` for remediation path resolution.
- **UI is cached aggressively** — tell the user to hard-reload (`Cmd+Shift+R`) after UI edits.
- **Only `MISSING_KEY` is remediable.** Value/type mismatches and extra keys are reported only.
- Environment folders are assumed to share the same env names across services in a multi-service
  scan (env pickers browse using the first selected service / first pair).

---

## 6. Suggested next steps / open ideas (not yet done)

- Per-service env overrides (currently all services in a scan share one env pair).
- Auto-fix for `VALUE_MISMATCH` (currently missing keys only).
- Fuzzy/auto service-name matching for dual mode (explicitly declined so far).
- Surface remediation failures per-key in the UI (bulk response has `results[]` but UI only alerts a summary).
