"""Prove that sealed reference-task outputs remain scoreable after uninstall."""

import argparse
import importlib.util
import json
from pathlib import Path

from gymts import GymTS
from gymts.contracts import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--require-absent", action="store_true")
    args = parser.parse_args()
    if args.require_absent and importlib.util.find_spec("gymts_minimal_demo") is not None:
        raise RuntimeError("Uninstall gymts-minimal-demo before checking its absence")
    root = Path(args.root).resolve()
    receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
    scoring = json.loads((root / "score-spec.json").read_text(encoding="utf-8"))
    archived = json.loads((root / "candidate-declaration.json").read_text(encoding="utf-8"))

    def unavailable(spec):
        raise RuntimeError("The uninstalled Candidate cannot be executed during scoring")

    with GymTS(root=root, data_home=root / "datasets", cache_home=root / "cache") as gym:
        # AutoBenchTS checks the original public declaration even without inference.
        # Restore metadata only; no algorithm or executable backend is recovered.
        manifest = archived["manifest"]
        gym.schemas.register(manifest["params_schema_ref"], archived["params_schema"])
        gym.registries.candidates.register(manifest, unavailable)
        report = gym.autobench.score(scoring)
        actual = {run_id: {"result": digest(gym.records.get_run(run_id)["result"]),
                           "events": digest(gym.records.get_run(run_id)["events"])} for run_id in receipt["run_ids"]}
        if report["verdict"] != "pass" or actual != receipt["sealed_fingerprints"]:
            raise RuntimeError("Independent rescoring failed or changed sealed Run evidence")
        print(json.dumps({"verdict": report["verdict"], "evaluation_id": report["evaluation_id"],
                          "same_run_ids": True, "run_evidence_unchanged": True,
                          "archived_declaration_restored": True,
                          "optional_adapter_required": False}, indent=2))


if __name__ == "__main__":
    main()
