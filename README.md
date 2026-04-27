# DriftGuard: Configuration Health & Drift Management System

DriftGuard is a production-grade configuration drift detection and remediation system. It is designed to intelligently monitor, compare, and fix configuration discrepancies across different service environments (e.g., UAT vs. Production) stored in Git repositories. 

Unlike traditional diff tools, DriftGuard understands the **semantic structure** of YAML and Properties files. It can safely merge missing keys, intelligently inherit quoting styles ("Mirror Styling"), and surgically version-control your files before making any modifications.

---

## ✨ Key Features
- **Semantic Comparison:** Parses `.yml` and `.properties` files as data objects, not raw text, ignoring trivial whitespace differences.
- **Surgical Backup Strategy:** Automatically rotates backups based on your Git history (`_backup`, `_backup_1`, etc.) **only** for the files you are actively fixing. It never spams your repository with aggressive global backups.
- **Mirror Styling:** When fixing a missing key, DriftGuard inspects the source baseline file to figure out if it used single quotes, double quotes, or no quotes, and perfectly mirrors that style into the target file.
- **Noise Reduction Rules:** Uses `rules.yaml` to define environment-specific keys (like DB passwords) that *should* drift, or to flat-out ignore noisy keys.

---

## 🚀 Step-by-Step Local Setup Guide

Follow these instructions to get DriftGuard running on your local machine from scratch.

### 1. Prerequisites
Ensure you have the following installed on your system:
* **Python 3.9+** (`python --version`)
* **Git** (`git --version`)
* A Bash-compatible terminal (Terminal on Mac/Linux, Git Bash or WSL on Windows).

### 2. Set Up the Virtual Environment
We strongly recommend running DriftGuard inside an isolated Python virtual environment to prevent dependency conflicts.

```bash
# 1. Navigate to the root directory of the DriftGuard project
cd /path/to/PropertyDrift

# 2. Create the virtual environment (named 'venv')
python3 -m venv venv

# 3. Activate the virtual environment
# On Mac/Linux:
source venv/bin/activate
# On Windows (Command Prompt):
# venv\Scripts\activate.bat
```

*(You will know this worked if your terminal prompt now starts with `(venv)`)*

### 3. Install Dependencies
With your virtual environment active, install the required packages:

```bash
pip install -r requirements.txt
```

### 4. Running the Application
DriftGuard runs a FastAPI backend and a static HTML/JS frontend out of the box.

```bash
# Start the server
python server.py
```
* **Dashboard:** Open your web browser and go to: `http://localhost:8000`
* **API Documentation:** Go to: `http://localhost:8000/docs`

---

## 💻 How to Use DriftGuard

### 1. Clone or Update a Repository
1. Open the UI and look at the **"Target Repository"** section.
2. Enter the clone URL of a repository (e.g., `prod-cloud-config`) and click **Clone / Update Repo**.
3. DriftGuard will execute a `git clone` (or `git pull` if it already exists) into the `data/repos/` folder.
*Note: This strictly pulls the environment natively, it does not touch or create backup files during clone.*

### 2. Run a Configuration Scan
1. Select the **Service** (e.g., `jfl-locator`), the **Baseline Environment**, and the **Target Environment**.
2. Click **Run Scan**. 
3. DriftGuard will parse every file and calculate a drift score, isolating keys that are missing or mismatched.

### 3. Remediate (Fix) Drifts
1. In the scan results, click the **Fix** button next to a missing key.
2. DriftGuard executes the **Surgical Backup Strategy**:
   * It checks the *Git HEAD* of the file you are fixing.
   * If an old backup already exists and your file has been updated via a recent `git pull`, it intelligently archives the old backup as `filename_backup_1.ext`.
   * It creates a fresh, pristine `filename_backup.ext` showing the state before the fix was applied.
3. DriftGuard safely injects the missing key into the file.

---

## 📂 Directory Structure

```text
├── config/                 # Service & ignore rules
│   └── rules.yaml          # Custom drift & severity rules
├── data/                   # Persistent storage layer
│   ├── repos/              # Local clones of your configuration Git repositories
│   └── driftguard.db       # SQLite database storing historical scan metrics
├── logs/                   # System audit logs
│   └── driftguard.log      # Detailed operational trace
├── src/
│   ├── api/                # FastAPI Endpoints & Data Models
│   ├── core/               # Engine, GitManager, Remediator, Ruleset
│   └── ui/                 # Static web assets (HTML/CSS/JS)
├── server.py               # Main uvicorn entry point
└── requirements.txt        # Python dependencies
```

---

## 🔐 The Surgical Backup Strategy Explained
DriftGuard refuses to blindly overwrite your files. When you apply a fix to `application.properties`:

1. **`application_backup.properties`:** This file represents the absolute latest "pristine" code as you pulled it from Git.
2. **`application_backup_1.properties`:** If you later run `git pull` from your remote server, and then trigger *another* fix, the system detects that your pristine file evolved. It moves your old archive to `_backup_1` and recreates the primary `_backup`.
3. **Targeted Precision:** This process **only occurs** on the exact file you clicked "Fix" on. Untouched services in your repository remain perfectly clean for your `git status` commits.

---

## 🛠 Operation & Debugging Scripts

If you need to restart or clean the environment during active development:

**Force Restart Server (Clears blocked ports):**
```bash
lsof -i :8000 -t | xargs kill -9 && venv/bin/python server.py
```

**Reset the Database:**
If you want to clear your historical scan metrics:
```bash
rm data/driftguard.db
# (The system will automatically recreate the database schema on next startup)
```

**Live Tail Logs:**
Keep a terminal window open tracking exactly what the engine is evaluating:
```bash
tail -f logs/driftguard.log
```

## ⚙️ Customizing the Rules Engine (`rules.yaml`)
You can fine-tune what DriftGuard considers an error by modifying `config/rules.yaml`.

* **`ignore_keys`**: Add keys like `last_updated_time` or `server.port` to this array to instruct the engine to completely skip comparing them.
* **`env_aware_keys`**: Use this for things like `db.password`. If these values differ between servers, it will flag them as `INFO` instead of a drift error, acknowledging that they *should* be different.
