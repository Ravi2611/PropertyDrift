import os
from typing import List, Dict

class RepoScanner:
    @staticmethod
    def _is_config_file(filename: str) -> bool:
        if "_backup" in filename: # Ignore remediation backups
            return False
        return filename.endswith(('.yml', '.yaml', '.properties'))

    @staticmethod
    def scan_service(env_path: str) -> List[str]:
        files = []
        for f in os.listdir(env_path):
            if RepoScanner._is_config_file(f):
                files.append(f)
        return files

    @staticmethod
    def get_services(repo_path: str) -> List[str]:
        """Returns a list of service directories in the repository."""
        services = []
        for item in os.listdir(repo_path):
            if os.path.isdir(os.path.join(repo_path, item)) and not item.startswith('.'):
                services.append(item)
        return services

    @staticmethod
    def get_environments(repo_path: str, service: str, sub_path: str = "") -> List[Dict]:
        """Returns immediate items in the service/env path with metadata for navigation."""
        service_path = os.path.join(repo_path, service)
        
        # Check for 'stage' convention
        stage_path = os.path.join(service_path, "stage")
        root_search = stage_path if os.path.isdir(stage_path) else service_path
        
        target_path = os.path.join(root_search, sub_path)
        if not os.path.exists(target_path) or not os.path.isdir(target_path):
            return []
            
        items = []
        for item in os.listdir(target_path):
            if item.startswith('.') or item == "stage":
                continue
                
            full_path = os.path.join(target_path, item)
            if os.path.isdir(full_path):
                # Check for config files in this directory
                has_configs = any(f.endswith(('.yml', '.yaml', '.properties', '.cfg')) and "_backup" not in f 
                                 for f in os.listdir(full_path))
                # Check for subdirectories
                has_subdirs = any(os.path.isdir(os.path.join(full_path, sub)) and not sub.startswith('.') 
                                 for sub in os.listdir(full_path))
                
                items.append({
                    "name": item,
                    "is_folder": has_subdirs,
                    "is_env": has_configs
                })
        
        return sorted(items, key=lambda x: x["name"])
