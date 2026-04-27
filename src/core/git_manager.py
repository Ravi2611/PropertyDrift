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
