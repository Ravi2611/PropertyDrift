# DriftGuard 🛡️

> **Automated Configuration Drift Detection & Remediation for GitLab-hosted config repositories.**

DriftGuard scans your Git-hosted configuration repositories, detects when environments have drifted apart (missing keys, value mismatches, type mismatches), and can automatically fix them — with optional GitLab Merge Request creation.

---

## Table of Contents

- [What is Configuration Drift?](#what-is-configuration-drift)
- [How DriftGuard Works](#how-driftguard-works)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Local Setup](#local-setup)
- [Configuration — rules.yaml](#configuration--rulesyaml)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [API Reference](#api-reference)
- [Typical Workflow](#typical-workflow)
- [Supported File Types](#supported-file-types)
- [Drift Types & Severity](#drift-types--severity)
- [Remediation — How it Works](#remediation--how-it-works)
- [Git & MR Integration](#git--mr-integration)
- [Logs](#logs)
- [Deployment](#deployment)

---

## What is Configuration Drift?

In microservice architectures, configuration files exist per environment — `s0`, `s1`, `uat`, `prod`. Over time, keys get added to one environment but forgotten in others. This is **configuration drift**.

**Example:**

```yaml
# s0/application.yml (baseline - correct)
server:
  port: 8080
  timeout: 30
feature:
  payments: true

# s1/application.yml (drifted - missing keys!)
server:
  port: 8080
```

DriftGuard detects that `server.timeout` and `feature.payments` are **missing** in `s1` and can automatically insert them with the correct environment-aware values.

---

## How DriftGuard Works

```
┌─────────────────────────────────────────────────────────┐
│                      DriftGuard Flow                     │
└─────────────────────────────────────────────────────────┘

  1. Clone Repo          2. Select Service        3. Run Scan
  ┌──────────┐           ┌──────────────┐         ┌──────────────────┐
  │ GitLab   │──clone──▶ │ post-order/  │──scan──▶│ Compare s0 vs s1 │
  │ Config   │           │ payment/     │         │ Compare keys,    │
  │ Repo     │           │ inventory/   │         │ values, types    │
  └──────────┘           └──────────────┘         └────────┬─────────┘
                                                           │
                                                           ▼
  5. Create GitLab MR    4. Remediate            Drift Report
  ┌──────────────────┐   ┌──────────────┐        ┌──────────────────┐
  │ driftguard-fix-  │◀──│ Insert key   │◀───────│ CRITICAL: 3 keys │
  │ 1234567890       │   │ Transform    │        │ WARNING:  2 keys │
  │ (auto branch)    │   │ value for s1 │        │ INFO:     1 key  │
  └──────────────────┘   └──────────────┘        └──────────────────┘
```

---

## Project Structure

```
driftguard/
├── server.py                # ⚡ Entrypoint — starts uvicorn, loads .env, serves UI
├── src/
│   ├── api/
│   │   ├── main.py          # FastAPI app — all endpoints
│   │   └── models.py        # SQLModel database models (DriftRecord, ScanHistory)
│   ├── core/
│   │   ├── engine.py        # Drift comparison logic — compares env files
│   │   ├── scanner.py       # Repo scanner — discovers services and environments
│   │   ├── parser.py        # YAML and .properties file parsers (flattens to dot-notation)
│   │   ├── remediator.py    # Writes missing keys back into config files
│   │   ├── rules.py         # Rules engine — ignore keys, severity, value transforms
│   │   ├── git_manager.py   # Git operations — clone, checkout, push, MR creation
│   │   └── logger.py        # Shared logger (console + file)
│   └── ui/                  # Frontend — static files served at /
│       └── index.html       # (and other static assets)
├── config/
│   └── rules.yaml           # ⚠️ Required — drift rules, ignore lists, env mappings
├── .env                     # Local environment variables (never commit this)
├── .env.example             # Template for required environment variables
├── data/
│   └── repos/               # Cloned repositories are stored here (auto-created)
├── logs/
│   └── driftguard.log       # Application logs (auto-created)
└── README.md
```

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | |
| pip | Latest | |
| git | Any recent | Must be available in `PATH` |
| GitLab access | — | PAT token needed for MR creation |

---

## Local Setup

### 1. Clone the DriftGuard repository

```bash
git clone https://gitlab.your-domain.com/your-team/driftguard.git
cd driftguard
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up `config/rules.yaml`

This file is **required** for the app to function. See the [Configuration](#configuration--rulesyaml) section below for the full format.

```bash
# At minimum, create an empty valid rules file
mkdir -p config
touch config/rules.yaml
```

### 5. Create a `.env` file (required)

DriftGuard uses `python-dotenv` — create a `.env` file in the project root and it will be loaded automatically on startup. **This step is mandatory:** all Git operations (clone, fetch, pull, push) authenticate with these credentials, and DriftGuard will refuse to talk to a remote without them.

```env
GIT_USERNAME=your-gitlab-username
GIT_TOKEN=your-personal-access-token
GIT_DOMAIN=gitlab.your-domain.com
```

> ⚠️ **Never commit `.env` to Git.** Make sure it is in your `.gitignore`.
>
> ℹ️ If these are missing, cloning/scanning fails immediately with a `Missing required Git credentials` error — this is intentional (no fallback to ambient Git auth).

A `.env.example` template is provided in the repo — copy it to get started:

```bash
cp .env.example .env
# Then edit .env with your actual values
```

### 6. Run the application

```bash
venv/bin/python server.py
```

This single command:
- Loads your `.env` file automatically
- Starts the FastAPI backend on port `8051/driftguard`
- Serves the frontend UI from `src/ui/` at `http://localhost:8051/`

---

### Stopping the Application

If the port is already in use (e.g. a previous instance is still running), kill it first:

```bash
lsof -i :8051 -t | xargs kill -9 && venv/bin/python server.py
```

This kills any process on port 8051/driftguard and immediately restarts the app.

---

## Configuration — rules.yaml

`config/rules.yaml` is the brain of DriftGuard. It controls what gets ignored, how severity is assigned, and how values are transformed during remediation.

> ⚠️ **This file has nothing to do with Docker or deployment.** It is purely runtime configuration that tells DriftGuard how to interpret differences between environments.

### What each section does

| Section | Purpose |
|---------|---------|
| `ignore_keys` | Completely skip these keys during comparison — no drift reported |
| `ignore_patterns` | Regex-based key ignore — any key matching the pattern is skipped |
| `env_aware_keys` | Keys where **value differences are expected** across environments (e.g. `db.url` will always differ — that's normal). These are marked `INFO` instead of flagging as drift |
| `normalizations` | Strip volatile parts of a value before comparing (e.g. strip the hostname from a JDBC URL so only the database name is compared) |
| `severity` | Override the default severity for specific keys |
| `env_mappings` | Maps each environment name to its ALB URL — used during **remediation** to automatically swap the correct ALB when inserting a missing key into a target environment |

### Current Configuration

```yaml
# DriftGuard Rules Configuration

ignore_keys:
#  - "server.port"   # Uncomment to ignore port differences

# Keys where value differences are EXPECTED across environments.
# DriftGuard will not flag these as drift — they are environment-specific by design.
env_aware_keys:
  - "db.url"
  - "db.password"

# Keys matching these regex patterns are completely ignored during scanning.
ignore_patterns:
  - ".*timestamp.*"
  - ".*metrics.*"

# Normalization — strip volatile parts before comparing values.
# This strips the hostname from db.url so only the database name is compared.
# e.g. "jdbc:mysql://host-s0/mydb" and "jdbc:mysql://host-s1/mydb" are treated as equal.
normalizations:
  - pattern: 'db.url'
    regex: 'jdbc:mysql://[^/]+/(.+)'
    replace: 'jdbc:mysql://{HOST_REMOVED}/\1'

# Severity overrides — these keys get a fixed severity regardless of diff type.
severity:
  CRITICAL:
    - "feature-flags.new-ui"
    - "db.user"
  WARNING:
    - "server.timeout"

# ALB mappings per environment.
# Used during REMEDIATION ONLY — when a missing key's value contains an ALB URL,
# DriftGuard swaps it to the correct ALB for the target environment automatically.
# This is NOT used for drift detection — it does not affect what gets flagged.
env_mappings:
  s0:
    alb: "http://internal-s0-int-alb-1898657965.ap-south-1.elb.amazonaws.com"
  s1:
    alb: "http://internal-s1-int-alb-268696201.ap-south-1.elb.amazonaws.com"
  s2:
    alb: "http://internal-s2-int-alb-962471675.ap-south-1.elb.amazonaws.com"
  s3:
    alb: "http://internal-s3-int-alb-51824138.ap-south-1.elb.amazonaws.com"
  s4:
    alb: "http://internal-s4-int-alb-94887976.ap-south-1.elb.amazonaws.com"
  s7:
    alb: "http://internal-s7-int-alb-2056119716.ap-south-1.elb.amazonaws.com"
  s8:
    alb: "http://internal-s8-int-alb-386223465.ap-south-1.elb.amazonaws.com"
  s9:
    alb: "http://internal-s9-int-alb-1290036311.ap-south-1.elb.amazonaws.com"
  dev4:
    alb: "http://internal-dev4-int-alb-2036348797.ap-south-1.elb.amazonaws.com"
  dev5:
    alb: "http://internal-dev5-int-alb-860243805.ap-south-1.elb.amazonaws.com"
  uat:
    alb: "http://internal-uat-alb-internal-533139398.ap-south-1.elb.amazonaws.com"
  prod:
    alb: "http://internal-prod-alb-internal-1242406384.ap-south-1.elb.amazonaws.com"
  hongs-s0:
    alb: "https://hongs-s0-backend-int-alb.hongskitchen.in"
  hongs-s1:
    alb: "https://hongs-s1-backend-int-alb.hongskitchen.in"
  hongs-prod:
    alb: "https://hongs-prod-backend-int-alb.hongskitchen.in"
  nextgen-s1:
    alb: "http://nextgen-s1-internal.dominosindia.in"
  nextgen-s2:
    alb: "http://nextgen-s2-internal.dominosindia.in"
```

### Adding a New Environment

When a new environment is spun up (e.g. `s10`), add its ALB entry under `env_mappings`:

```yaml
env_mappings:
  s10:
    alb: "http://internal-s10-int-alb-XXXXXXXXXX.ap-south-1.elb.amazonaws.com"
```

No code changes needed — DriftGuard picks it up automatically.

### Severity Logic (Default, before overrides)

| Drift Type | Default Severity |
|------------|-----------------|
| `MISSING_FILE` | CRITICAL |
| `MISSING_KEY` | CRITICAL |
| `EXTRA_KEY` | WARNING |
| `EXTRA_FILE` | INFO |
| `VALUE_MISMATCH` | INFO |
| `TYPE_MISMATCH` | WARNING |

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GIT_USERNAME` | **Yes** | — | GitLab username |
| `GIT_TOKEN` | **Yes** | — | GitLab Personal Access Token with `api` and `write_repository` scope |
| `GIT_DOMAIN` | **Yes** | `gitlab.dominosindia.in` | Your GitLab instance domain |

> **Note:** All three variables are **required for every Git operation** — clone, fetch, pull, and push all authenticate with these credentials. DriftGuard will **not** fall back to your machine's ambient/cached Git credentials. If any of them are missing, cloning and scanning will fail immediately with a clear `Missing required Git credentials` error. Credentials are injected into the remote URL only for the duration of each command and are **never persisted** to the cloned repo's `.git/config`. Both `http://` and `https://` remotes are supported.

### Creating a GitLab Personal Access Token

1. Go to GitLab → Profile → Access Tokens
2. Create a token with scopes: `api`, `read_repository`, `write_repository`
3. Set it as `GIT_TOKEN`

---

## Running the Application

### Development

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8051 --reload
```

### Production

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8051 --workers 2
```

### Access the Application

| URL | What it is |
|-----|-----------|
| `http://localhost:8051` | **DriftGuard UI** — the frontend dashboard |
| `http://localhost:8051/driftguard/docs` | **Swagger UI** — interactive API documentation |
| `http://localhost:8051/driftguard/redoc` | **ReDoc** — read-only API documentation |
| `http://localhost:8051/driftguard/health` | Health check |



---

## API Reference

### System

#### `GET /health`
Health check endpoint. Returns `{"status": "ok"}` if the server is up.

---

### Repository

#### `POST /repo/clone`
Clones a remote Git config repository locally. If already cloned, fetches latest changes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_url` | string | ✅ | Full HTTPS URL of the GitLab repo |

**Example:**
```bash
curl -X POST "http://localhost:8051/driftguard/repo/clone?repo_url=https://gitlab.your-domain.com/team/stage-cloud-config.git"
```

**Response:**
```json
{
  "status": "success",
  "repo_name": "stage-cloud-config",
  "branches": ["master", "feature/xyz"],
  "default_branch": "master",
  "services": ["post-order", "payment", "inventory"]
}
```

---

#### `GET /repo/{repo_name}/services`
Lists all service directories inside a cloned repository.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_name` | path | ✅ | Name of the cloned repo folder |
| `branch` | query | ❌ | Branch to checkout before scanning (defaults to HEAD) |

**Example:**
```bash
curl "http://localhost:8051/driftguard/repo/stage-cloud-config/services?branch=master"
```

---

#### `GET /repo/{repo_name}/envs`
Browses environment folders under a service. Supports hierarchical navigation.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_name` | path | ✅ | Repo folder name |
| `service` | query | ✅ | Service name (e.g. `post-order`) |
| `branch` | query | ✅ | Git branch to use |
| `sub_path` | query | ❌ | Sub-path to drill into (e.g. `stage`) |

**Example:**
```bash
curl "http://localhost:8051/driftguard/repo/stage-cloud-config/envs?service=post-order&branch=master"
```

**Response:**
```json
[
  {"name": "s0", "is_folder": false, "is_env": true},
  {"name": "s1", "is_folder": false, "is_env": true},
  {"name": "uat", "is_folder": false, "is_env": true}
]
```

---

### Scanning

DriftGuard supports two comparison modes:

| Mode | Endpoint | Compares |
|------|----------|----------|
| **Single-repo** | `GET /scan` | Two environments **inside one repo** (e.g. `s0` vs `s1` of the same service) |
| **Dual-repo** | `GET /scan/dual` | The same-purpose service folder **across two different repos** (e.g. `repo-a/post-order/s0` vs `repo-b/post-order-web/prod`) |

Both modes persist to the same `ScanHistory` / `DriftRecord` tables. Remediation (`/remediate`, `/remediate/bulk`) works identically for both — in dual-repo mode, writes and any Merge Request go to the **target repo only**; the baseline repo is never modified.

#### `GET /scan` — single-repo mode
Runs a drift scan comparing a baseline environment to a target environment inside **one** cloned repo.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo_name` | query | ✅ | `mock_repo` | Cloned repo name |
| `service` | query | ✅ | `service-A` | Service to scan |
| `baseline_env` | query | ✅ | `s0` | Reference environment |
| `target_env` | query | ✅ | `s1` | Environment being checked |
| `baseline_branch` | query | ❌ | — | Git branch to checkout before scanning |
| `services` | query | ❌ | — | Comma-separated list of services to scan in one run (e.g. `post-order,payment,inventory`). Overrides `service`. All share the same env pair. |

**Example (single service):**
```bash
curl "http://localhost:8051/driftguard/scan?repo_name=stage-cloud-config&service=post-order&baseline_env=s0&target_env=s1"
```

**Example (multiple services in one scan):**
```bash
curl "http://localhost:8051/driftguard/scan?repo_name=stage-cloud-config&services=post-order,payment,inventory&baseline_env=s0&target_env=s1"
```

All selected services land under one `scan_id`; each drift record is attributed to its own service, and Fix All fixes across every service in one MR.

---

#### `GET /scan/dual` — dual-repo mode
Compares configuration files between two **different** cloned repositories.

Use this when the baseline and target live in separate repos (e.g. a shared config repo vs a service-specific repo, or a legacy vs modern deployment). Both repos must already be cloned via `POST /repo/clone`. Service folder names can differ between the two repos — this endpoint does no auto-matching, it compares exactly the two folders you point it at.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `baseline_repo` | query | ✅ | Local repo name (from `/repo/clone`) — **read-only** reference side |
| `target_repo` | query | ✅ | Local repo name — the side that will receive any fixes/MR |
| `baseline_service` | query | ✅ | Service folder inside `baseline_repo` (e.g. `post-order`) |
| `target_service` | query | ✅ | Service folder inside `target_repo` (e.g. `post-order-web`) |
| `baseline_env` | query | ✅ | Env folder inside the baseline service |
| `target_env` | query | ✅ | Env folder inside the target service |
| `baseline_branch` | query | ❌ | Branch to check out on `baseline_repo` before reading |
| `target_branch` | query | ❌ | Branch to check out on `target_repo` before reading |
| `baseline_services` | query | ❌ | Comma-separated baseline services (index-aligned with `target_services`). Overrides `baseline_service`. |
| `target_services` | query | ❌ | Comma-separated target services (same length as `baseline_services`). Overrides `target_service`. |

**Multi-pair example:**
```bash
curl "http://localhost:8051/driftguard/scan/dual?\
baseline_repo=repo-a&target_repo=repo-b&\
baseline_services=post-order,payment&target_services=post-order-web,payment-web&\
baseline_env=s0&target_env=prod"
```

Each pair is compared independently and all results land under one `scan_id`. Every drift record records both its baseline service and target service, so remediation writes to the correct target folder per record.

**Example:**
```bash
curl "http://localhost:8051/driftguard/scan/dual?\
baseline_repo=stage-cloud-config&target_repo=prod-cloud-config&\
baseline_service=post-order&target_service=post-order-web&\
baseline_env=s0&target_env=prod&\
baseline_branch=master&target_branch=release"
```

The response shape matches `/scan` and additionally reports `"mode": "dual"`.

**Response:**
```json
{
  "status": "success",
  "scan_id": 42,
  "drifts_found": 3,
  "drifts": [
    {
      "id": 101,
      "service": "post-order",
      "env": "s1",
      "file": "application.yml",
      "key": "feature.payments",
      "base_value": "true",
      "target_value": null,
      "diff_type": "MISSING_KEY",
      "severity": "CRITICAL",
      "drift_score": 10
    }
  ]
}
```

---

#### `GET /results`
Queries all stored drift records with optional filters.

| Parameter | Type | Description |
|-----------|------|-------------|
| `service` | query | Filter by service name |
| `env` | query | Filter by environment |
| `severity` | query | Filter by severity (`CRITICAL`, `WARNING`, `INFO`) |

---

#### `GET /matrix`
Returns a `service → environment → drift score` matrix. Used for heatmap dashboards.

| Parameter | Type | Description |
|-----------|------|-------------|
| `scan_id` | query | Optional — filter matrix to a specific scan |

**Response:**
```json
{
  "post-order": {
    "s1": {"score": 20, "timestamp": "2024-01-15T10:30:00"},
    "uat": {"score": 0, "timestamp": "2024-01-15T10:30:00"}
  }
}
```

---

#### `GET /scans`
Lists all past scan runs, most recent first.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | query | `50` | Max number of scans to return |

---

#### `GET /scans/{scan_id}/drifts`
Returns all drift records for a specific scan run.

---

### Remediation

#### `POST /remediate`
Fixes a single `MISSING_KEY` drift by inserting the key into the target config file.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `record_id` | query | ✅ | — | ID of the drift record to fix |
| `create_mr` | query | ❌ | `false` | Push fix and open GitLab MR |

**Example:**
```bash
# Fix locally only
curl -X POST "http://localhost:8051/driftguard/remediate?record_id=101"

# Fix and open MR
curl -X POST "http://localhost:8051/remediate?record_id=101&create_mr=true"
```

---

#### `POST /remediate/bulk`
Fixes **all** `MISSING_KEY` drifts in a scan in one shot.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `scan_id` | query | ✅ | — | Scan ID from `/scan` response |
| `create_mr` | query | ❌ | `false` | Push all fixes in one MR |

**Example:**
```bash
curl -X POST "http://localhost:8051/driftguard/driftguard/remediate/bulk?scan_id=42&create_mr=true"
```

**Response:**
```json
{
  "status": "success",
  "total": 3,
  "remediated": 3,
  "message": "3/3 keys remediated. MR Created on branch: driftguard-fix-1705312200",
  "results": [
    {"key": "feature.payments", "success": true},
    {"key": "server.timeout", "success": true},
    {"key": "db.pool.size", "success": true}
  ]
}
```

---

## Typical Workflow

### Single-repo mode

```
Step 1 — Clone your config repo
POST /repo/clone?repo_url=https://gitlab.your-domain.com/team/stage-cloud-config.git

Step 2 — Browse services
GET /repo/stage-cloud-config/services

Step 3 — Browse environments for a service
GET /repo/stage-cloud-config/envs?service=post-order&branch=master

Step 4 — Run a drift scan
GET /scan?repo_name=stage-cloud-config&service=post-order&baseline_env=s0&target_env=s1

Step 5 — Review results (note the scan_id from Step 4)
GET /scans/42/drifts

Step 6a — Fix everything at once + open MR
POST /remediate/bulk?scan_id=42&create_mr=true

Step 6b — Or fix individual issues
POST /remediate?record_id=101&create_mr=false
```

### Dual-repo mode

```
Step 1 — Clone BOTH repos
POST /repo/clone?repo_url=https://gitlab.your-domain.com/team/repo-a.git
POST /repo/clone?repo_url=https://gitlab.your-domain.com/team/repo-b.git

Step 2 — Browse services + envs on each side (same endpoints as single mode)
GET /repo/repo-a/services
GET /repo/repo-a/envs?service=post-order&branch=master
GET /repo/repo-b/services
GET /repo/repo-b/envs?service=post-order-web&branch=release

Step 3 — Run a dual-repo drift scan
GET /scan/dual?baseline_repo=repo-a&target_repo=repo-b\
             &baseline_service=post-order&target_service=post-order-web\
             &baseline_env=s0&target_env=prod\
             &baseline_branch=master&target_branch=release

Steps 4–6 — Identical to single mode.
Fixes and any Merge Request will land on repo-b (the target). repo-a is never touched.
```

**UI:** the dashboard has a **Single Repo / Two Repos** toggle at the top of the controls card. In Two Repos mode you get a **Repository A (Baseline)** panel and a **Repository B (Target)** panel, each with its own clone input, branch, service, and env selectors.

---

## Supported File Types

| Extension | Parser | Notes |
|-----------|--------|-------|
| `.yml` | YAML (ruamel + PyYAML) | Nested keys flattened to dot-notation |
| `.yaml` | YAML (ruamel + PyYAML) | Same as above |
| `.properties` | Properties parser | `key=value` format |

Files containing `_backup` in their name are automatically ignored by the scanner.

---

## Drift Types & Severity

| Drift Type | Meaning | Default Severity |
|------------|---------|-----------------|
| `MISSING_KEY` | Key exists in baseline but not in target | CRITICAL |
| `EXTRA_KEY` | Key exists in target but not in baseline | WARNING |
| `MISSING_FILE` | Entire file exists in baseline but not in target | CRITICAL |
| `EXTRA_FILE` | File exists in target but not in baseline | INFO |
| `VALUE_MISMATCH` | Key exists in both but values differ | INFO |
| `TYPE_MISMATCH` | Key exists in both but types differ (e.g. string vs int) | WARNING |

> Severity can be overridden per key in `config/rules.yaml`.

---

## Remediation — How it Works

DriftGuard only auto-remediates `MISSING_KEY` drifts. Here is exactly what happens:

1. **Backup** — A `_backup` copy of the target file is created from Git HEAD before any changes
2. **Transform** — The baseline value is transformed for the target environment using `env_mappings` in `rules.yaml` (e.g. ALB hostnames, env tokens like `s0` → `s1`)
3. **Style Mirror** — The key's formatting style (quotes, indentation) is mirrored from the baseline file using `ruamel.yaml` (preserves your existing YAML style)
4. **Inject** — The key is inserted into the correct position in the YAML hierarchy or appended to `.properties`
5. **MR (optional)** — If `create_mr=true`, a new branch `driftguard-fix-{timestamp}` is created and pushed to GitLab with an auto-opened Merge Request targeting `master`

### Backup Rotation

If a file has already been remediated and the backup is stale (differs from current Git HEAD), the old backup is rotated to `_backup_1`, `_backup_2`, etc. and a fresh backup is created.

---

## Git & MR Integration

DriftGuard uses GitLab's push options to create Merge Requests automatically:

```
git push -o merge_request.create -o merge_request.target=master origin driftguard-fix-1234567
```

### Credential Setup

Credentials are injected at push time via the environment variables `GIT_USERNAME` and `GIT_TOKEN`. The authenticated URL is temporarily set on `remote.origin.url` before pushing.

> **Only HTTPS remotes are supported** for MR creation. SSH remotes will fall back to system-level credentials.

---

## Logs

All logs are written to two places simultaneously:

| Destination | Level | Location |
|-------------|-------|----------|
| Console (stdout) | INFO and above | Terminal output |
| File | DEBUG and above | `logs/driftguard.log` |

Log format:
```
[2024-01-15 10:30:00] [INFO] [API] Request: GET /scan | repo=stage-cloud-config | service=post-order
[2024-01-15 10:30:01] [DEBUG] [Engine] Analyzing file: application.yml
[2024-01-15 10:30:01] [INFO] [API] Success: GET /scan | scan_id=42 | drifts_found=3
```

Named loggers per module: `API`, `Engine`, `Git`, `Rules`, `Remediator`

---

## Deployment

### Deployment Checklist (for Infra Team)

```
Service Name    : DriftGuard
Repo            : driftguard
Language        : Python 3.10+
Entrypoint      : venv/bin/python server.py
Health Check    : GET /health → 200 OK
Port            : 8051/driftguard
Internal/External: Internal only
Resource Strategy: Low (minimal replicas, no autoscaling needed)

Environment Variables (Secrets):
  GIT_USERNAME  = <gitlab-username>
  GIT_TOKEN     = <gitlab-pat-token>
  GIT_DOMAIN    = <your-gitlab-domain>
```

---

*Built with FastAPI · SQLModel · ruamel.yaml · GitLab Push Options*