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
    service: str
    env: str
    file: str
    key: str
    base_value: Any
    target_value: Any
    diff_type: str # MISSING_KEY, EXTRA_KEY, VALUE_MISMATCH, TYPE_MISMATCH, MISSING_FILE, EXTRA_FILE
    severity: str
    value_type: Optional[str] = None

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

    def _resolve_env_path(self, repo_path: str, service: str, env: str) -> str:
        service_path = os.path.join(repo_path, service)
        stage_path = os.path.join(service_path, "stage", env)
        if os.path.exists(stage_path):
            return stage_path
        return os.path.join(service_path, env)

    def compare_environments(self, repo_path: str, service: str, baseline_env: str, target_env: str) -> List[DriftDiff]:
        logger.info(f"Comparing environments: service={service} ({baseline_env} -> {target_env})")
        base_dir = self._resolve_env_path(repo_path, service, baseline_env)
        target_dir = self._resolve_env_path(repo_path, service, target_env)
        
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
                    # Reuse the logic from scanner if possible, otherwise use local check
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
                    service=service, env=target_env, file=filename, key='',
                    base_value=None, target_value=None,
                    diff_type='EXTRA_FILE', severity=self.rule_manager.get_severity('', 'EXTRA_FILE')
                ))
                continue
            
            if filename not in target_files:
                all_diffs.append(DriftDiff(
                    service=service, env=target_env, file=filename, key='',
                    base_value=None, target_value=None,
                    diff_type='MISSING_FILE', severity=self.rule_manager.get_severity('', 'MISSING_FILE')
                ))
                continue
                
            base_data = parse_config_file(os.path.join(base_dir, filename)) or {}
            target_data = parse_config_file(os.path.join(target_dir, filename)) or {}
            
            all_diffs.extend(self.compare_files(service, target_env, filename, base_data, target_data))
            
        return all_diffs

    def calculate_drift_score(self, diffs: List[DriftDiff]) -> int:
        # Simple scoring: CRITICAL=10, WARNING=2, INFO=0
        score = 0
        for d in diffs:
            if d.severity == 'CRITICAL': score += 10
            elif d.severity == 'WARNING': score += 2
        return score
