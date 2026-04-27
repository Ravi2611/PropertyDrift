import yaml
from typing import Dict, Any, Optional
import os

class ConfigParser:
    """Base class for configuration parsers."""
    
    @staticmethod
    def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
        """Flattens a nested dictionary into a single-level dictionary with dot-notation keys."""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(ConfigParser.flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

class YamlParser(ConfigParser):
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        """Parses a YAML file and flattens it."""
        try:
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)
                if data is None:
                    return {}
                return ConfigParser.flatten_dict(data)
        except Exception as e:
            print(f"Error parsing YAML file {file_path}: {e}")
            return {}

class PropertiesParser(ConfigParser):
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        """Parses a .properties file."""
        properties = {}
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith(('#', '!')):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            properties[key.strip()] = value.strip()
        except Exception as e:
            print(f"Error parsing properties file {file_path}: {e}")
            return {}
        return properties

def get_parser(extension: str):
    if extension in ['.yml', '.yaml']:
        return YamlParser
    elif extension == '.properties':
        return PropertiesParser
    return None

def parse_config_file(file_path: str) -> Optional[Dict[str, Any]]:
    _, ext = os.path.splitext(file_path)
    parser = get_parser(ext)
    if parser:
        return parser.parse(file_path)
    return None
