"""Public organization API/CLI and actual data-to-experiment evidence linkage."""
from copy import deepcopy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.cli import main as cli
from gymts.contracts import GymTSError
from gymts.contracts.organization import ATTEMPT, EVENT, GROUP, REQUEST


ROOT = Path(__file__).resolve().parents[1]
LOAD = importlib.util.spec_from_file_location("organization_example", ROOT / "examples/experiment_organization.py")
EXAMPLE = importlib.util.module_from_spec(LOAD)
LOAD.loader.exec_module(EXAMPLE)


class ExperimentOrganizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gymts-group-api-")
        self.root = Path(self.temporary.name)
        self.gym = GymTS(self.root / "runs", data_home=self.root / "data", cache_home=self.root / "cache")

    def tearDown(self):
        self.gym.close()
        self.temporary.cleanup()

    def prepare(self):
        self.gym.experiments.register_executor(EXAMPLE.component("example.catalog-forecast"), EXAMPLE.forecast_from_catalog)
        self.gym.experiments.register_executor(EXAMPLE.component("example.observed-outcomes"), EXAMPLE.observed_outcomes)
        return EXAMPLE.prepare(self.gym)

    def test_real_five_stage_workflow_and_reopen_without_executors(self):
        group = self.prepare()
        self.gym.schemas.validate(GROUP, group)
        self.assertEqual(group, self.gym.experiments.register(group))
        state = self.gym.experiments.execute(group["group_id"], revision=group["revision"])
        self.assertEqual("succeeded", state["status"])
        self.assertEqual(5, len(state["attempts"]))
        self.assertEqual(1, len(state["runs"]))
        self.assertEqual(3, len(state["runs"][0]["associations"]))
        self.assertEqual(1, len(self.gym.records.list_runs(dataset_id="organization/ramp")))
        self.assertEqual(1, len(self.gym.experiments.query(dataset_id="organization/recorded")))
        self.assertEqual([], self.gym.experiments.query(dataset_id="unknown"))
        for attempt in state["attempts"]:
            self.gym.schemas.validate(ATTEMPT, attempt)
            self.gym.schemas.validate(REQUEST, self.gym.artifacts.read_json(attempt["request_ref"]))
        events = self.gym.experiments.store.events(group["group_id"], group["revision"])
        self.assertEqual(list(range(1, len(events) + 1)), [event["seq"] for event in events])
        for event in events:
            self.gym.schemas.validate(EVENT, event)
        self.assertEqual(events[2:], self.gym.experiments.store.events(group["group_id"], group["revision"], after_seq=2))
        self.gym.close()
        self.gym = GymTS(self.root / "runs", data_home=self.root / "data", cache_home=self.root / "new-cache")
        with patch.object(self.gym, "run", side_effect=AssertionError("Successful stage must not execute again")):
            reopened = self.gym.experiments.execute(group["group_id"], revision=group["revision"])
        self.assertEqual(state, reopened)
        self.assertEqual(1, len(self.gym.experiments.query(status="succeeded")))

    def test_missing_executor_and_output_binding_failures_are_recorded(self):
        ref = EXAMPLE.component("test.missing")
        group = self.gym.experiments.register({"group_id": "test/binding", "name": "binding", "stages": [
            {"stage_id": "work", "executor_ref": ref, "spec": {}, "outputs": {"required": "/missing"}}]})
        failed = self.gym.experiments.execute(group["group_id"], revision=group["revision"])
        self.assertEqual("unsupported_capability", failed["attempts"][0]["error"]["code"])
        self.gym.experiments.register_executor(ref, lambda spec, gym: {"actual": 1})
        second = self.gym.experiments.execute(group["group_id"], revision=group["revision"], retry_failed=True)
        self.assertEqual("failed", second["status"])
        self.assertIsNotNone(second["attempts"][-1]["result_ref"])
        self.assertEqual({"actual": 1}, self.gym.artifacts.read_json(second["attempts"][-1]["result_ref"]))

    def test_scoring_an_existing_run_adds_association_without_changing_ownership(self):
        group = self.prepare()
        first = self.gym.experiments.execute(group["group_id"], revision=group["revision"])
        run_id = first["runs"][0]["run_id"]
        before = self.gym.records.get_run(run_id)
        scoring = next(attempt for attempt in first["attempts"] if attempt["stage_id"] == "score")
        spec = self.gym.artifacts.read_json(scoring["request_ref"])["spec"]
        second = self.gym.experiments.register({"group_id": "test/existing-evidence", "name": "Existing evidence", "stages": [
            {"stage_id": "score", "executor_ref": EXAMPLE.component("gymts.score"), "spec": spec}]})
        result = self.gym.experiments.execute(second["group_id"], revision=second["revision"])
        self.assertEqual("succeeded", result["status"])
        self.assertEqual([run_id], [run["run_id"] for run in result["runs"]])
        self.assertEqual(before, self.gym.records.get_run(run_id))
        self.assertEqual(2, len(self.gym.experiments.query(dataset_id="organization/ramp")))
        self.assertEqual(4, len(self.gym.records.list_runs(attempt_id=result["attempts"][0]["attempt_id"])[0]["associations"]))

    def test_interleaved_execution_cannot_claim_a_stage_from_an_outdated_view(self):
        reference = EXAMPLE.component("test.once")
        calls = []
        executor = lambda spec, gym: (calls.append("called") or {"value": 1})
        self.gym.experiments.register_executor(reference, executor)
        group = self.gym.experiments.register({"group_id": "test/interleaved", "name": "Concurrent claim", "stages": [
            {"stage_id": "work", "executor_ref": reference, "spec": {}}]})
        original = self.gym.experiments.store.begin
        def another_caller_finishes_before_claim(*args, **options):
            with GymTS(self.root / "runs", data_home=self.root / "data", cache_home=self.root / "other-cache") as other:
                other.experiments.register_executor(reference, executor)
                other.experiments.execute(group["group_id"], revision=group["revision"])
            return original(*args, **options)
        with patch.object(self.gym.experiments.store, "begin", side_effect=another_caller_finishes_before_claim):
            with self.assertRaisesRegex(GymTSError, "Stage changed"):
                self.gym.experiments.execute(group["group_id"], revision=group["revision"])
        self.assertEqual(["called"], calls)
        self.assertEqual(1, len(self.gym.experiments.inspect(group["group_id"], revision=group["revision"])["attempts"]))

    def test_invalid_graphs_and_fixed_revision_conflicts(self):
        stage = {"stage_id": "one", "executor_ref": EXAMPLE.component("gymts.run"), "spec": {}}
        for stages in ([dict(stage, depends_on=["absent"])], [stage, deepcopy(stage)],
                       [dict(stage, inputs={"x": {"kind": "stage_output", "stage_id": "one", "output": "x"}})]):
            with self.subTest(stages=stages), self.assertRaises(GymTSError):
                self.gym.experiments.register({"group_id": "test/invalid", "name": "invalid", "stages": stages})
        group = self.gym.experiments.register({"group_id": "test/fixed", "name": "fixed", "stages": [stage]})
        changed = dict(group, name="changed")
        with self.assertRaises(GymTSError):
            self.gym.experiments.register(changed)

    def test_core_cli_can_register_execute_query_and_read_events(self):
        config = {"group_id": "cli/counter", "name": "CLI counter", "stages": [
            {"stage_id": "execute", "executor_ref": EXAMPLE.component("gymts.run"),
             "spec": json.loads((ROOT / "examples/counter_experiment.json").read_text())}]}
        file = self.root / "group.json"
        file.write_text(json.dumps(config))
        flags = ["--store", str(self.root / "runs"), "--data-home", str(self.root / "data"), "--cache-home", str(self.root / "cache")]
        def call(arguments):
            output, error = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                code = cli(flags + arguments)
            self.assertEqual(0, code, error.getvalue())
            return json.loads(output.getvalue())
        definition = call(["experiments", "register", str(file)])
        identity = [definition["group_id"], "--revision", definition["revision"]]
        state = call(["experiments", "run"] + identity)
        self.assertEqual("succeeded", state["status"])
        self.assertEqual(state, call(["experiments", "info"] + identity))
        self.assertEqual(1, len(call(["experiments", "list", "--group-id", "cli/counter"])["experiments"]))
        self.assertEqual(1, len(call(["runs", "--group-id", "cli/counter"])["runs"]))
        self.assertEqual(4, len(call(["experiments", "events"] + identity)["events"]))


if __name__ == "__main__":
    unittest.main()
