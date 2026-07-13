import os
import shutil
from collections.abc import Mapping
from typing import Any, Dict, Optional
from ruamel.yaml import YAML
from src.core.logger import setup_logger

logger = setup_logger("Remediator")

class ConfigRemediator:
    def __init__(self):
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)

    def create_backup(self, file_path: str, repo_path: Optional[str] = None, git_manager: Optional[Any] = None) -> str:
        """Creates or rotates a backup of the file to match the current Git-pristine state (HEAD)."""
        base, ext = os.path.splitext(file_path)
        backup_path = f"{base}_backup{ext}"
        
        pristine_content = None
        if repo_path and git_manager:
            rel_path = os.path.relpath(file_path, repo_path)
            pristine_content = git_manager.get_file_content_at_branch(repo_path, "HEAD", rel_path)

        if not os.path.exists(backup_path):
            if pristine_content:
                logger.info(f"Creating initial backup from Git HEAD: {backup_path}")
                with open(backup_path, 'w') as f:
                    f.write(pristine_content)
            else:
                logger.info(f"Creating initial backup from current file: {backup_path}")
                shutil.copy2(file_path, backup_path)
        else:
            # If we have pristine content, check if our backup is stale
            if pristine_content:
                try:
                    with open(backup_path, 'r') as f:
                        current_backup_content = f.read()
                    
                    if current_backup_content != pristine_content:
                        logger.info(f"Stale backup detected for {file_path}. Rotating archives.")
                        # Rotate: _backup -> _backup_N
                        counter = 1
                        while True:
                            archived_name = f"{base}_backup_{counter}{ext}"
                            if not os.path.exists(archived_name):
                                os.rename(backup_path, archived_name)
                                break
                            counter += 1
                        
                        # Create new pristine backup
                        with open(backup_path, 'w') as f:
                            f.write(pristine_content)
                except Exception as e:
                    logger.warning(f"Failed to verify/rotate backup for {file_path}: {e}")
            else:
                logger.debug(f"Backup already exists and no Git HEAD content available: {backup_path}")
                
        return backup_path

    def remediate_missing_key(self, file_path: str, key: str, value: Any,
                             baseline_file_path: Optional[str] = None,
                             repo_path: Optional[str] = None,
                             git_manager: Optional[Any] = None,
                             create_backup: bool = True) -> bool:
        """Adds a missing key to the target file, optionally mirroring style from baseline and versioning backup.

        When `create_backup` is False, the pre-write `_backup` file is not
        created or rotated. Any existing backup files on disk from prior runs
        are left untouched.
        """
        logger.info(f"Remediating missing key '{key}' in {file_path} (backup={'on' if create_backup else 'off'})")
        if not os.path.exists(file_path):
            logger.error(f"Target file not found for remediation: {file_path}")
            return False

        _, ext = os.path.splitext(file_path)

        if create_backup:
            self.create_backup(file_path, repo_path=repo_path, git_manager=git_manager)
        else:
            logger.debug(f"Skipping backup creation for {file_path} (create_backup=False)")

        # If baseline provided, try to extract styled value
        styled_value = value
        if baseline_file_path and os.path.exists(baseline_file_path) and ext in ['.yml', '.yaml']:
            try:
                with open(baseline_file_path, 'r') as f:
                    base_data = self.yaml.load(f) or {}
                    # Navigate to find the key in baseline
                    keys = key.split('.')
                    curr = base_data
                    for k in keys:
                        if isinstance(curr, dict) and k in curr:
                            curr = curr[k]
                        else:
                            curr = None
                            break
                    if curr is not None:
                        styled_value = curr
                        logger.debug(f"Mirroring style for '{key}' from baseline")
            except Exception as e:
                logger.warning(f"Could not extract style from baseline: {e}")

        if ext in ['.yml', '.yaml']:
            return self._remediate_yaml(file_path, key, styled_value)
        elif ext == '.properties':
            return self._remediate_properties(file_path, key, value)
        
        return False

    def _remediate_yaml(self, file_path: str, key: str, value: Any) -> bool:
        try:
            logger.debug(f"Remediator: Starting YAML edit for {file_path}")
            logger.debug(f"Remediator: Opening file for reading")
            with open(file_path, 'r') as f:
                data = self.yaml.load(f) or {}
            logger.debug(f"Remediator: File parsed into memory structure ({type(data).__name__})")

            # Handle nested keys (e.g., 'db.pool.size')
            keys = key.split('.')
            current = data
            logger.debug(f"Remediator: Navigating hierarchy for key path: {keys}")
            for part in keys[:-1]:
                if part not in current:
                    logger.debug(f"Remediator: Creating missing parent group '{part}'")
                    current[part] = {}
                elif current[part] is None:
                    # Parent key exists but is null (e.g. `menu:` with all its
                    # children commented out). Promote it to an empty mapping so
                    # we can nest under it, instead of crashing on None.
                    logger.debug(f"Remediator: Parent group '{part}' is null; promoting to empty mapping")
                    current[part] = {}
                elif not isinstance(current[part], Mapping):
                    # Parent exists as a scalar/list — we can't safely nest a key
                    # underneath it without destroying existing data.
                    logger.error(
                        f"Cannot insert '{key}': parent '{part}' is a "
                        f"{type(current[part]).__name__}, not a mapping, in {file_path}"
                    )
                    return False
                current = current[part]
                logger.debug(f"Remediator: Entered group '{part}'")

            target_key = keys[-1]
            logger.debug(f"Remediator: Injecting key '{target_key}' with value '{value}'")
            current[target_key] = value
            
            logger.debug(f"Remediator: Preparing to commit changes to disk")
            with open(file_path, 'w') as f:
                self.yaml.dump(data, f)
            logger.info(f"YAML remediation successful: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error remediating YAML ({file_path}): {e}")
            return False

    def _remediate_properties(self, file_path: str, key: str, value: Any) -> bool:
        try:
            logger.debug(f"Remediator: Starting Properties edit for {file_path}")
            logger.debug(f"Remediator: Preparing to append '{key}={value}'")
            with open(file_path, 'a') as f:
                # Ensure there's a newline before appending
                f.write(f"\n{key}={value}\n")
            logger.info(f"Properties remediation successful: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error remediating Properties ({file_path}): {e}")
            return False
