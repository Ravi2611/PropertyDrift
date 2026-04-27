import yaml
import re
from typing import Dict, List, Any, Optional
from src.core.logger import setup_logger

logger = setup_logger("Rules")

class RuleManager:
    def __init__(self, rules_path: str):
        self.rules_path = rules_path
        self.rules = self._load_rules()
        self.ignore_keys = set(self.rules.get('ignore_keys') or [])
        self.env_aware_keys = set(self.rules.get('env_aware_keys') or [])
        self.ignore_patterns = [re.compile(p) for p in (self.rules.get('ignore_patterns') or [])]
        self.normalizations = self.rules.get('normalizations') or []
        self.severity_rules = self.rules.get('severity') or {}

    def _load_rules(self) -> Dict[str, Any]:
        try:
            with open(self.rules_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error loading rules from {self.rules_path}: {e}")
            return {}

    def is_ignored(self, key: str) -> bool:
        if key in self.ignore_keys:
            return True
        for pattern in self.ignore_patterns:
            if pattern.match(key):
                return True
        return False

    def is_env_aware(self, key: str) -> bool:
        return key in self.env_aware_keys

    def normalize(self, key: str, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        
        for norm in self.normalizations:
            if re.match(norm.get('pattern', ''), key):
                replacement = norm.get('replace', '')
                value = re.sub(norm.get('regex', ''), replacement, value)
        return value

    def get_severity(self, key: str, diff_type: str) -> str:
        # Check custom rules for specific keys first
        for sev, keys in self.severity_rules.items():
            if key in keys:
                return sev

        # Default logic based on diff type
        if diff_type == 'MISSING_FILE': return 'CRITICAL'
        if diff_type == 'MISSING_KEY': return 'CRITICAL'
        if diff_type == 'EXTRA_FILE': return 'INFO'
        if diff_type == 'EXTRA_KEY': return 'WARNING'
        if diff_type == 'VALUE_MISMATCH':
            if self.is_env_aware(key):
                return 'INFO'
            return 'INFO' # User requested Different value as Info
            
        return 'WARNING'

    def transform_value(self, key: str, value: Any, target_env: str, baseline_env: str) -> Any:
        """Transforms a value from baseline to target (e.g. s0 -> s1 or ALB mapping)."""
        if not isinstance(value, str):
            return value

        remediation_cfg = self.rules.get('remediation', {})
        static_mappings = remediation_cfg.get('static_mappings', [])
        
        # 1. Try static mappings (e.g. ALBs)
        remediation_cfg = self.rules.get('remediation', {})
        static_mappings = remediation_cfg.get('static_mappings', [])
        
        logger.debug(f"RuleManager: Processing {len(static_mappings)} static mappings for {key}")
        for mapping in static_mappings:
            pattern = mapping.get('key_pattern')
            if pattern and (re.search(pattern, key, re.IGNORECASE) or re.search(pattern, value, re.IGNORECASE)):
                envs = mapping.get('environments', {})
                
                # Check for direct match first, then substring match
                match_val = envs.get(target_env)
                if not match_val:
                    for e_short, e_full in envs.items():
                        if e_short.lower() in target_env.lower():
                            match_val = e_full
                            break
                
                if match_val:
                    logger.info(f"RuleManager: Static mapping HIT for {key} -> {target_env}")
                    # Append suffix if original value had a path (e.g. /catalog-service/)
                    suffix = ""
                    if ".com/" in value:
                        suffix = value.split(".com/")[1]
                    
                    final_val = match_val if not suffix else f"{match_val.rstrip('/')}/{suffix}"
                    return final_val
        
        # 2. Try Smart Swap (e.g. replace s0 with s1)
        if remediation_cfg.get('enable_smart_swap', True):
            search_str = baseline_env
            for short_env in ["s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "dev4", "dev5"]:
                if short_env in baseline_env:
                    search_str = short_env
                    break
            
            replace_str = target_env
            for short_env in ["s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "dev4", "dev5"]:
                if short_env in target_env:
                    replace_str = short_env
                    break

            pattern = re.compile(re.escape(search_str), re.IGNORECASE)
            transformed = pattern.sub(replace_str, value)
            return transformed
            
        return value
