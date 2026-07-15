import subprocess
import os
import re
import shutil
from urllib.parse import urlsplit, urlunsplit, quote
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

    def _require_credentials(self):
        """Returns (user, token, domain) or raises if credentials are missing.

        Every network git operation (clone/fetch/pull/push) goes through here,
        so DriftGuard will refuse to talk to a remote without configured creds
        instead of silently falling back to ambient/cached git auth.
        """
        git_user = os.environ.get("GIT_USERNAME")
        git_token = os.environ.get("GIT_TOKEN")
        git_domain = os.environ.get("GIT_DOMAIN", "gitlab.dominosindia.in")
        missing = [
            name for name, val in (
                ("GIT_USERNAME", git_user),
                ("GIT_TOKEN", git_token),
                ("GIT_DOMAIN", git_domain),
            ) if not val
        ]
        if missing:
            raise RuntimeError(
                "Missing required Git credentials: "
                + ", ".join(missing)
                + ". Set them in your .env (GIT_USERNAME, GIT_TOKEN, GIT_DOMAIN) "
                + "before any clone/fetch/pull/push."
            )
        return git_user, git_token, git_domain

    def _authenticated_url(self, url):
        """Injects the configured credentials into an http(s) remote URL.

        Works for both http:// and https:// remotes. Any credentials already
        embedded in the URL are stripped first, and the token is URL-encoded so
        special characters don't corrupt the URL.
        """
        git_user, git_token, git_domain = self._require_credentials()
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise RuntimeError(
                f"Unsupported remote scheme in '{url}'. Only http/https remotes "
                "can be authenticated with GIT_USERNAME/GIT_TOKEN."
            )
        # Strip any user:pass@ that may already be embedded in the host part.
        host = parts.netloc.rsplit("@", 1)[-1]
        if git_domain and git_domain not in host:
            logger.warning(
                f"Remote host '{host}' does not match GIT_DOMAIN '{git_domain}'; "
                "injecting credentials anyway."
            )
        netloc = f"{quote(git_user, safe='')}:{quote(git_token, safe='')}@{host}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    def _remote_url(self, repo_path):
        """Reads the (clean) origin URL stored in the repo's git config."""
        res = subprocess.run(
            ["git", "-C", repo_path, "config", "--get", "remote.origin.url"],
            capture_output=True, text=True,
        )
        return res.stdout.strip()

    def _authenticated_remote_url(self, repo_path):
        """Builds an authenticated origin URL for an already-cloned repo."""
        remote_url = self._remote_url(repo_path)
        if not remote_url:
            raise RuntimeError(f"Could not determine origin URL for repo at {repo_path}")
        return self._authenticated_url(remote_url)

    def _redact(self, text):
        """Strips any embedded `user:token@` secrets from text before it is
        surfaced to logs or the UI, so credentials never leak."""
        if not text:
            return text
        token = os.environ.get("GIT_TOKEN")
        if token:
            text = text.replace(token, "***")
        # Also mask any user:pass@ that made it into a URL in the message.
        return re.sub(r"://[^/@\s]+:[^/@\s]+@", "://***:***@", text)

    def _run_git(self, args, action):
        """Runs a git command, capturing output. On failure raises a clean,
        credential-redacted RuntimeError containing git's actual stderr so the
        real cause (e.g. auth denied) is visible instead of a bare exit code."""
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"{action} failed: {self._redact(detail)}")
        return result

    def clone_or_update(self, repo_url):
        repo_path = self._get_repo_path(repo_url)
        auth_url = self._authenticated_url(repo_url)
        if os.path.exists(repo_path):
            # Update existing — fetch via authenticated URL, keep stored remote clean.
            logger.info(f"Updating existing repo: {repo_url} at {repo_path}")
            self._run_git(
                ["git", "-C", repo_path, "fetch", auth_url,
                 "+refs/heads/*:refs/remotes/origin/*", "--prune", "--tags"],
                action="Fetch",
            )
        else:
            # Clone new via authenticated URL, then scrub the token from config.
            logger.info(f"Cloning new repo: {repo_url} to {repo_path}")
            self._run_git(["git", "clone", auth_url, repo_path], action="Clone")
            subprocess.run(
                ["git", "-C", repo_path, "remote", "set-url", "origin", repo_url],
                check=True,
            )
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
        
        # Try to pull latest via authenticated URL, but don't fail if it's not
        # possible (e.g. no upstream). Credentials are required to reach the remote.
        logger.debug(f"Pulling latest for {branch}")
        auth_url = self._authenticated_remote_url(repo_path)
        subprocess.run(["git", "-C", repo_path, "pull", auth_url, branch], capture_output=True)

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

        # 4. Build an authenticated push URL (works for http:// and https://).
        # Credentials are required — this raises if they are not configured.
        # We push to the URL directly so the token is never persisted to config.
        auth_url = self._authenticated_remote_url(repo_path)
        logger.info("Using configured Git credentials for push.")

        # 5. Push with GitLab MR options
        logger.info(f"Pushing branch {branch_name} and opening Merge Request...")
        push_cmd = [
            "git", "-C", repo_path, "push",
            "-o", "merge_request.create",
            "-o", "merge_request.target=master",
            auth_url, branch_name
        ]
        
        push_res = subprocess.run(push_cmd, capture_output=True, text=True)
        
        if push_res.returncode != 0:
            detail = self._redact(push_res.stderr)
            logger.error(f"Push failed: {detail}")
            raise Exception(f"Git push failed: {detail}")
            
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
