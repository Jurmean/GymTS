"""Run the independent example from an installed wheel; data stays in GymTS."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from gymts import GymTS
from gymts.contracts import digest
from gymts_organization_demo import group_definition, register


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", required=True)
    parser.add_argument("--csv", required=True, help="Existing official ETTh1.csv; never downloaded by this example")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--count", type=int, default=32)
    args = parser.parse_args()
    root = Path(args.work)
    root.mkdir(parents=True, exist_ok=True)
    full = Path(args.csv).read_bytes()
    table = csv.DictReader(io.StringIO(full.decode("utf-8")))
    selected = [row for _, row in zip(range(args.count), table)]
    if len(selected) != args.count or args.count < 4:
        raise ValueError("Select at least four existing hourly observations")
    compact = io.StringIO()
    writer = csv.DictWriter(compact, fieldnames=table.fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(selected)
    origin = {"repository": "https://github.com/zhouhaoyi/ETDataset", "revision": args.source_revision,
        "file": "ETT-small/ETTh1.csv", "full_file_sha256": hashlib.sha256(full).hexdigest(),
        "selection": {"start": 0, "count": args.count, "column": "OT"}}
    with GymTS(root / "store", data_home=root / "data", cache_home=root / "cache") as gym:
        register(gym)
        raw_ref = gym.artifacts.save_artifact(compact.getvalue().encode(), {"media_type": "text/csv"})
        group = gym.experiments.register(group_definition(raw_ref, origin))
        view = gym.experiments.execute(group["group_id"], revision=group["revision"])
        (root / "organization-view.json").write_text(json.dumps(view, indent=2))
        if view["status"] != "succeeded":
            raise RuntimeError("An organization stage failed; inspect organization-view.json")
        attempts = {attempt["stage_id"]: attempt for attempt in view["attempts"]}
        score = gym.artifacts.read_json(attempts["score"]["result_ref"])
        expected = gym.artifacts.read_json(attempts["references"]["result_ref"])
        dataset = gym.artifacts.read_json(attempts["import"]["result_ref"])["dataset"]
        receipt = {"group_id": group["group_id"], "revision": group["revision"], "dataset": dataset,
            "score_spec": gym.artifacts.read_json(attempts["score"]["request_ref"])["spec"],
            "score_report": score, "expected_mae": expected["expected_mae"], "expected_count": expected["expected_count"],
            "run_ids": [run["run_id"] for run in view["runs"]], "origin": origin, "selected_csv_ref": raw_ref,
            "organization_events": len(gym.experiments.events(group["group_id"], revision=group["revision"])),
            "sealed_fingerprints": {run["run_id"]: {"result": digest(gym.records.get_run(run["run_id"])["result"]),
                "events": digest(gym.records.get_run(run["run_id"])["events"])} for run in view["runs"]},
            "public_rows_hash": digest(list(gym.environment_ts.datasets.load_dataset(**dataset, purpose="runtime")))}
        (root / "receipt.json").write_text(json.dumps(receipt, indent=2))
        print(json.dumps({"group_id": group["group_id"], "revision": group["revision"], "status": view["status"],
            "stages": len(view["stages"]), "runs": len(view["runs"]), "receipt": str(root / "receipt.json")}))


if __name__ == "__main__":
    main()
