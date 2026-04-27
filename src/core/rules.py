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
        """Transforms a value from baseline to target by swapping exact tokens and ALBs."""
        if not isinstance(value, str):
            return value

        env_mappings = self.rules.get('env_mappings', {})
        if not env_mappings:
            return value

        # 1. Identify which tokens belong to baseline and which belong to target
        # Sort them by length descending so we match 'hongs-s0' before 's0'
        sorted_keys = sorted(env_mappings.keys(), key=len, reverse=True)
        
        base_tokens = [k for k in sorted_keys if k in baseline_env]
        target_tokens = [k for k in sorted_keys if k in target_env]
        
        new_value = value
        
        # 2. Extract specific ALBs and Tokens to swap
        # We pair up the matched tokens. If baseline is `uat/hongs-uat` and target is `stage/hongs-s0`
        # base_tokens = ['hongs-uat', 'uat'], target_tokens = ['hongs-s0', 's0']
        
        # Determine the primary token mapping
        for i in range(min(len(base_tokens), len(target_tokens))):
            b_tok = base_tokens[i]
            t_tok = target_tokens[i]
            
            b_alb = env_mappings.get(b_tok, {}).get('alb', '')
            t_alb = env_mappings.get(t_tok, {}).get('alb', '')
            
            # Substitute ALB if matched
            if b_alb and b_alb in new_value:
                new_value = new_value.replace(b_alb, t_alb)
                logger.info(f"RuleManager: Swapped ALB {b_alb} -> {t_alb}")
            
            # Substitute explicit tokens
            if b_tok in new_value:
                new_value = new_value.replace(b_tok, t_tok)
                logger.info(f"RuleManager: Swapped Token {b_tok} -> {t_tok}")

        return new_value
