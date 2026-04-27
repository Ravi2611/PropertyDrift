import json
import argparse
import os
from src.core.parser import parse_config_file
from src.core.rules import RuleManager
from src.core.engine import DriftEngine, DriftDiff
from src.core.scanner import RepoScanner
from dataclasses import asdict

def main():
    parser = argparse.ArgumentParser(description="DriftGuard: Configuration Drift Detection")
    parser.add_argument("--repo", default="mock_repo", help="Path to the configuration repository")
    parser.add_argument("--rules", default="config/rules.yaml", help="Path to the rules configuration")
    parser.add_argument("--baseline", default="s0", help="Baseline environment (e.g., s0)")
    parser.add_argument("--output", default="drift_results.json", help="Output JSON file")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.repo):
        print(f"Error: Repository path {args.repo} does not exist.")
        return

    rule_manager = RuleManager(args.rules)
    engine = DriftEngine(rule_manager)
    scanner = RepoScanner()
    
    services = scanner.get_services(args.repo)
    all_results = []
    
    for service in services:
        envs = scanner.get_environments(args.repo, service)
        if args.baseline not in envs:
            print(f"Skipping {service}: Baseline {args.baseline} not found.")
            continue
            
        for env in envs:
            if env == args.baseline:
                continue
            
            print(f"Scanning {service}/{env} against {args.baseline}...")
            diffs = engine.compare_environments(args.repo, service, args.baseline, env)
            
            score = engine.calculate_drift_score(diffs)
            
            for d in diffs:
                res = asdict(d)
                res['drift_score'] = score
                all_results.append(res)
                
    with open(args.output, 'w') as f:
        json.dump(all_results, f, indent=2)
        
    print(f"Scan complete. Results saved to {args.output}")

if __name__ == "__main__":
    main()
