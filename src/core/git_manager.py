import subprocess
import os
import shutil
from src.core.logger import setup_logger

logger = setup_logger("Git")

class GitManager:
    def __init__(self, base_dir="data/repos"):
        self.base_dir = base_dir
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)

    def _get_repo_path(self, repo_url):
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        return os.path.join(self.base_dir, repo_name)

    def clone_or_update(self, repo_url):
        repo_path = self._get_repo_path(repo_url)
        if os.path.exists(repo_path):
            # Update existing
            logger.info(f"Updating existing repo: {repo_url} at {repo_path}")
            subprocess.run(["git", "-C", repo_path, "fetch", "--all"], check=True)
        else:
            # Clone new
            logger.info(f"Cloning new repo: {repo_url} to {repo_path}")
            subprocess.run(["git", "clone", repo_url, repo_path], check=True)
        return repo_path

    def list_branches(self, repo_path):
        result = subprocess.run(
            ["git", "-C", repo_path, "branch", "-r"],
            capture_output=True,
            text=True,
            check=True
        )
        branches = []
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line and "->" not in line:
                # Remove 'origin/' prefix
                branches.append(line.replace("origin/", ""))
        return branches

    def checkout(self, repo_path, branch):
        logger.info(f"Checkout/Pull: branch={branch} at {repo_path}")
        # Try checking out the branch.
        try:
            subprocess.run(["git", "-C", repo_path, "checkout", branch], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            # Maybe it's a remote branch not yet local
            try:
                logger.debug(f"Creating local branch {branch} from origin/{branch}")
                subprocess.run(["git", "-C", repo_path, "checkout", "-b", branch, f"origin/{branch}"], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                # If still fails, it might just be the current branch
                pass
        
        # Try to pull latest, but don't fail if it's not possible (e.g. no upstream)
        logger.debug(f"Pulling latest for {branch}")
        subprocess.run(["git", "-C", repo_path, "pull", "origin", branch], capture_output=True)

    def get_default_branch(self, repo_path):
        result = subprocess.run(
            ["git", "-C", repo_path, "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout.strip().replace("refs/remotes/origin/", "")
        
        # Fallback: check if master exists
        result = subprocess.run(["git", "-C", repo_path, "show-ref", "--verify", "refs/remotes/origin/master"], capture_output=True)
        if result.returncode == 0:
            return "master"
        return "main"

    def get_file_content_at_branch(self, repo_path, branch, file_path):
        """Gets file content from a specific branch without checking it out."""
        result = subprocess.run(
            ["git", "-C", repo_path, "show", f"{branch}:{file_path}"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return None
        return result.stdout

    def push_with_mr(self, repo_path: str, files: list, include_backups: bool = True) -> str:
        """Commits changes and creates a GitLab Merge Request.

        When `include_backups` is False, any `<name>_backup*.<ext>` files that
        happen to sit next to the modified files are NOT staged into the commit
        and are NOT restored back onto master after the push. Use this when the
        caller asked for a backup-free remediation.
        """
        import time
        branch_name = f"driftguard-fix-{int(time.time())}"

        logger.info(f"Creating new branch {branch_name} in {repo_path} (include_backups={include_backups})")

        # Ensure we are fully up to date and not on a detached HEAD before branching
        # (Assuming we are generally on 'master' or main here)

        # 1. Create and checkout new branch
        subprocess.run(["git", "-C", repo_path, "checkout", "-b", branch_name], check=True, capture_output=True)

        # 2. Add modified files
        for f in files:
            abs_f = os.path.abspath(f)
            subprocess.run(["git", "-C", repo_path, "add", abs_f], check=True, capture_output=True)

            if include_backups:
                # Also stage any sibling backup files (created during remediation)
                base, ext = os.path.splitext(abs_f)
                for file in os.listdir(os.path.dirname(abs_f)):
                    if file.startswith(os.path.basename(base) + "_backup") and file.endswith(ext):
                        backup_path = os.path.join(os.path.dirname(abs_f), file)
                        subprocess.run(["git", "-C", repo_path, "add", backup_path], check=True, capture_output=True)

        # 3. Commit
        commit_msg = "DriftGuard: Automated configuration remediation"
        result = subprocess.run(["git", "-C", repo_path, "commit", "-m", commit_msg], capture_output=True, text=True)
        
        if "nothing to commit" in result.stdout:
            logger.info("Nothing to commit. Skipping MR creation.")
            subprocess.run(["git", "-C", repo_path, "checkout", "-"], check=True, capture_output=True)
            return "No changes to commit"

        # 4. Handle Credentials and Push
        git_user = os.environ.get("GIT_USERNAME")
        git_token = os.environ.get("GIT_TOKEN")
        git_domain = os.environ.get("GIT_DOMAIN", "gitlab.dominosindia.in")
        
        if git_user and git_token:
            # We must get the repository slug out of the remote
            rem_res = subprocess.run(["git", "-C", repo_path, "config", "--get", "remote.origin.url"], capture_output=True, text=True)
            remote_url = rem_res.stdout.strip()
            
            # Simple assumption it is https
            if remote_url.startswith("https://"):
                authenticated_url = remote_url.replace(f"https://{git_domain}", f"https://{git_user}:{git_token}@{git_domain}")
                subprocess.run(["git", "-C", repo_path, "remote", "set-url", "origin", authenticated_url], check=True)
                logger.info("Injected Git credentials into remote origin.")
        
        # 5. Push with GitLab MR options
        logger.info(f"Pushing branch {branch_name} and opening Merge Request...")
        push_cmd = [
            "git", "-C", repo_path, "push",
            "-o", "merge_request.create",
            "-o", "merge_request.target=master",
            "origin", branch_name
        ]
        
        push_res = subprocess.run(push_cmd, capture_output=True, text=True)
        
        if push_res.returncode != 0:
            logger.error(f"Push failed: {push_res.stderr}")
            raise Exception(f"Git push failed: {push_res.stderr}")
            
        # 6. Restore the uncommitted state on master so the UI dashboard stays green
        logger.info("Restoring modified state locally to master to sync UI...")
        subprocess.run(["git", "-C", repo_path, "checkout", "master"], capture_output=True)
        for f in files:
            # f is like 'data/repos/stage-cloud-config/post-order/stage/s1/application.yml'
            # repo_path is 'data/repos/stage-cloud-config'
            rel_f = os.path.relpath(f, repo_path)
            
            # Bring the exact file changes into master's working tree
            res = subprocess.run(["git", "-C", repo_path, "checkout", branch_name, "--", rel_f], capture_output=True, text=True)
            if res.returncode != 0:
                logger.error(f"Failed to restore {rel_f}: {res.stderr}")
                    
            if include_backups:
                # Bring any related surgical backups back into master's working tree
                base, ext = os.path.splitext(f)
                for file in os.listdir(os.path.dirname(os.path.abspath(f))):
                    if file.startswith(os.path.basename(base) + "_backup") and file.endswith(ext):
                        backup_rel = os.path.relpath(os.path.join(os.path.dirname(os.path.abspath(f)), file), repo_path)
                        subprocess.run(["git", "-C", repo_path, "checkout", branch_name, "--", backup_rel], capture_output=True)
                    
        # Unstage them so they don't break the scanner or next branching operations
        subprocess.run(["git", "-C", repo_path, "reset"], capture_output=True)

        logger.info(f"Merge Request successfully opened for {branch_name}!")
        return branch_name
