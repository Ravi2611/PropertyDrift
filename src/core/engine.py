import os
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from .parser import parse_config_file
from .rules import RuleManager
from .logger import setup_logger

logger = setup_logger("Engine")

@dataclass
class DriftDiff:
    service: str  # TARGET service (used for target file path during remediation)
    env: str
    file: str
    key: str
    base_value: Any
    target_value: Any
    diff_type: str # MISSING_KEY, EXTRA_KEY, VALUE_MISMATCH, TYPE_MISMATCH, MISSING_FILE, EXTRA_FILE
    severity: str
    value_type: Optional[str] = None
    baseline_service: Optional[str] = None  # BASELINE service (may differ in dual mode)

class DriftEngine:
    def __init__(self, rule_manager: RuleManager):
        self.rule_manager = rule_manager

    def compare_files(self, service: str, env: str, filename: str, base_data: Dict[str, Any], target_data: Dict[str, Any]) -> List[DriftDiff]:
        diffs = []
        
        all_keys = set(base_data.keys()) | set(target_data.keys())
        ignored_count = 0
        
        for key in all_keys:
            if self.rule_manager.is_ignored(key):
                ignored_count += 1
                continue
            
            base_val = base_data.get(key)
            target_val = target_data.get(key)
            
            if key not in base_data:
                diffs.append(DriftDiff(
                    service=service, env=env, file=filename, key=key,
                    base_value=None, target_value=target_val,
                    value_type=type(target_val).__name__ if target_val is not None else None,
                    diff_type='EXTRA_KEY', severity=self.rule_manager.get_severity(key, 'EXTRA_KEY')
                ))
            elif key not in target_data:
                diffs.append(DriftDiff(
                    service=service, env=env, file=filename, key=key,
                    base_value=base_val, target_value=None,
                    value_type=type(base_val).__name__ if base_val is not None else None,
                    diff_type='MISSING_KEY', severity=self.rule_manager.get_severity(key, 'MISSING_KEY')
                ))
            else:
                norm_base = self.rule_manager.normalize(key, base_val)
                norm_target = self.rule_manager.normalize(key, target_val)
                
                if norm_base != norm_target:
                    # Check type mismatch
                    diff_type = 'VALUE_MISMATCH'
                    if type(base_val) != type(target_val):
                        diff_type = 'TYPE_MISMATCH'
                        
                    diffs.append(DriftDiff(
                        service=service, env=env, file=filename, key=key,
                        base_value=base_val, target_value=target_val,
                        value_type=type(base_val).__name__ if base_val is not None else None,
                        diff_type=diff_type, severity=self.rule_manager.get_severity(key, diff_type)
                    ))
        
        if ignored_count > 0:
            logger.debug(f"Ignored {ignored_count} keys in {filename} based on rules")
            
        return diffs

    @staticmethod
    def resolve_env_path(repo_path: str, service: str, env: str) -> str:
        """Resolve `{repo}/{service}/stage/{env}` if it exists, else `{repo}/{service}/{env}`.

        Public API used by both single-repo and dual-repo scans.
        """
        service_path = os.path.join(repo_path, service)
        stage_path = os.path.join(service_path, "stage", env)
        if os.path.exists(stage_path):
            return stage_path
        return os.path.join(service_path, env)

    def _resolve_env_path(self, repo_path: str, service: str, env: str) -> str:
        return self.resolve_env_path(repo_path, service, env)

    def compare_environments(self, repo_path: str, service: str, baseline_env: str, target_env: str) -> List[DriftDiff]:
        """Single-repo compare: same repo, same service, two env folders."""
        logger.info(f"Comparing environments: service={service} ({baseline_env} -> {target_env})")
        base_dir = self._resolve_env_path(repo_path, service, baseline_env)
        target_dir = self._resolve_env_path(repo_path, service, target_env)
        return self.compare_dirs(
            base_dir, target_dir,
            service_label=service, env_label=target_env,
            baseline_service_label=service,
        )

    def compare_dirs(self, base_dir: str, target_dir: str, service_label: str, env_label: str,
                     baseline_service_label: Optional[str] = None) -> List[DriftDiff]:
        """Compare two absolute env directories from anywhere on disk.

        `service_label` and `env_label` are attached to every DriftDiff for
        downstream persistence and remediation. In dual-repo mode the caller
        should pass the TARGET service name and TARGET env name here so
        remediation later resolves the correct target file path.

        `baseline_service_label` records which BASELINE service each diff came
        from (defaults to `service_label` for single-repo scans where they are
        the same). This lets remediation mirror style from the correct baseline
        folder even in multi-service dual-repo scans.
        """
        logger.debug(f"Resolved paths: base={base_dir}, target={target_dir}")

        if not os.path.exists(base_dir):
            logger.warning(f"Base environment directory not found: {base_dir}")
            return []

        def get_files_recursive(directory: str):
            config_files = set()
            if not os.path.exists(directory):
                return config_files
            for root, _, filenames in os.walk(directory):
                for f in filenames:
                    if (f.endswith(('.yml', '.yaml', '.properties')) and "_backup" not in f):
                        rel_path = os.path.relpath(os.path.join(root, f), directory)
                        config_files.add(rel_path)
            return config_files

        base_files = get_files_recursive(base_dir)
        target_files = get_files_recursive(target_dir)

        logger.debug(f"Files found: base={len(base_files)}, target={len(target_files)}")

        all_filenames = base_files | target_files
        all_diffs = []

        for filename in all_filenames:
            logger.debug(f"Analyzing file: {filename}")
            if filename not in base_files:
                all_diffs.append(DriftDiff(
                    service=service_label, env=env_label, file=filename, key='',
                    base_value=None, target_value=None,
                    diff_type='EXTRA_FILE', severity=self.rule_manager.get_severity('', 'EXTRA_FILE')
                ))
                continue

            if filename not in target_files:
                all_diffs.append(DriftDiff(
                    service=service_label, env=env_label, file=filename, key='',
                    base_value=None, target_value=None,
                    diff_type='MISSING_FILE', severity=self.rule_manager.get_severity('', 'MISSING_FILE')
                ))
                continue

            base_data = parse_config_file(os.path.join(base_dir, filename)) or {}
            target_data = parse_config_file(os.path.join(target_dir, filename)) or {}

            all_diffs.extend(self.compare_files(service_label, env_label, filename, base_data, target_data))

        baseline_label = baseline_service_label or service_label
        for d in all_diffs:
            d.baseline_service = baseline_label

        return all_diffs

    def calculate_drift_score(self, diffs: List[DriftDiff]) -> int:
        # Simple scoring: CRITICAL=10, WARNING=2, INFO=0
        score = 0
        for d in diffs:
            if d.severity == 'CRITICAL': score += 10
            elif d.severity == 'WARNING': score += 2
        return score
