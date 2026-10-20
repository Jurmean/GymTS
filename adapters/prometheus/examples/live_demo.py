"""Connect an explicitly configured Prometheus; never stop the attached service."""
import argparse
import json
from gymts_prometheus.demo import run_demo

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--store", required=True)
parser.add_argument("--endpoint", required=True)
parser.add_argument("--seconds", type=float, default=3)
parser.add_argument("--expected-value", type=float, help="Explicit independent demo reference; omit for unavailable gold")
args = parser.parse_args()
print(json.dumps(run_demo(args.store, args.endpoint, expected_value=args.expected_value, seconds=args.seconds), indent=2))
