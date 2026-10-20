"""Explicit standalone tools; experimental evaluation stays in AutoBenchTS."""
import argparse
import json
from pathlib import Path

from gymts import GymTS
from .tools import LibraryTSTools


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--timeout", type=float, default=120)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog")
    call = commands.add_parser("call")
    call.add_argument("spec", help="JSON {tool,arguments,params}")
    args = parser.parse_args(argv)
    with GymTS(args.store, integrations=("libraryts",)) as gym:
        tools = LibraryTSTools(gym.artifacts, {"repository": args.repository, "python": args.python}, timeout_seconds=args.timeout)
        result = tools.catalog() if args.command == "catalog" else tools.call(**json.loads(Path(args.spec).read_text()))
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0
