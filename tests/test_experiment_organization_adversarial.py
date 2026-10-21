"""Independent organization contracts, real Run recovery and data-purpose checks."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gymts import GymTS
from gymts.contracts import GymTSError, digest
from gymts.contracts.organization import GROUP
from gymts.contracts.resources import DATA_SOURCE
from gymts.contracts.schema import SchemaRegistry, register_core_schemas


ROOT = Path(__file__).resolve().parents[1]
CUSTOM = {"name": "test.organization-executor", "version": "1.0.0", "origin_ref": None}
RUN = {"name": "gymts.run", "version": "1.0.0", "origin_ref": None}
EVALUATE = {"name": "gymts.evaluate", "version": "1.0.0", "origin_ref": None}
ALL = {"allowed_uses": ["runtime", "evaluation", "training", "prepare", "dataset_build"], "training_allowed": True}
EVAL_ONLY = {"allowed_uses": ["evaluation"], "training_allowed": False}

# Independently read from the frozen F1 wheel source before organization existed.
# Existing schemas retain their exact definitions; new protocols are additive.
F1_SCHEMAS = {
    "gymts.artifact/1": "eeabe3583ca8f6dd2c5c029fc0149701cd48271dcc8fc3a9bd50948fdda1a340",
    "gymts.assembly-plan/1": "b2a9fb7b347959280c64b95feb8c4568d0b96bc1ffb9e8f13808943fcd2b4c3d",
    "gymts.autobench.benchmark/1": "d31bd70ab0730d79309f1acd4c476494a047d8ac2aa46b18793d4ba5bf1089cf",
    "gymts.component/1": "91e0ee72c11713c3bc5412544f05be219adaf85fb19b4f4d8c04bc483de083e0",
    "gymts.data-capture-row/1": "6093599694e8377c1682ae72a8bd7216786d8589f0dc658cf06b55add7db2a93",
    "gymts.data-capture/1": "765518e75414321eacae3a3c3445490d97d02d8464e5c8ad4fdb8d60e27dfaaa",
    "gymts.data-source/1": "db98194e81edf9e66532e8553506cba0b898ae14ec1b95670b0577c23f2fc053",
    "gymts.dataset-asset/1": "e8b3245d035a1db0d4a97d3989d1bba12f11482b8539236556c970e2ec8c86aa",
    "gymts.experiment/1": "bdcbbc068712de546225fd6900cf4c5351597281a5cf7bf1ad31c7c3984866d0",
    "gymts.extensions/1": "d746974fa9afd5e951f76f9af38954b0ad7f436f2120dc974da65e5ee39f856f",
    "gymts.json/1": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    "gymts.logprobs/1": "9708af6a581e23ecde949d922630ffb4527263f7706cc82a5f9e68099ed2aa0d",
    "gymts.model-call/1": "8b8d4a9411932599f6d072ceba5fe48538db2b226d8b8d4ef329dd8fd3aadb51",
    "gymts.native-inputs/1": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
    "gymts.payload/1": "ea914574d74eac9a397c3ed88cda3410fba2ee0cfc4b41e6f9a8305be9677819",
    "gymts.resource-provenance/1": "f7307bc315ec300ae847a5b8316a228d467247aa671483d1f682fe55356f65ac",
    "gymts.selection/1": "358a97bd5652cfce3babc79fd3670145bc5fb205b8a811450dca68df67d1f782",
    "gymts.source-dataset/1": "c3899478bfda012d39c2654cd6bdf89737cdaf506746d3a3ffc156dfc54aebdf",
    "gymts.source-dataset/2": "0d7cf093b698038f0d95fbafceeff8a0a52fc25804f3e672d7dfd13918c1fa74",
    "gymts.source-usage-policy/1": "d6b4b2548ee90896484016321cfbfc6acea7ee9cc2a0714ac245b88a63ea5658",
    "gymts.token-ids/1": "f7b95632ca0e591b9ca2d8d936d74fe41d1e15a73468410083c15b7419574860",
    "gymts.tool-call/1": "c867587ef7951ef24cdca801b9968583de91c54cc0cc28d169d9d0653d6dedfa",
    "gymts.view/1": "8f0b37d7a5f714f3ed788638bedc599175853448db73317da7e8a9e3da03ad1a",
}


class ExperimentOrganizationAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gymts-organization-contract-")
        self.directory = Path(self.temporary.name)
        self.gym = GymTS(self.directory / "store", data_home=self.directory / "data", cache_home=self.directory / "cache")
        self.catalog = self.gym.environment_ts.datasets

    def tearDown(self):
        self.gym.close()
        self.temporary.cleanup()

    def register(self, stages, name="independent-contract"):
        return self.gym.experiments.register({"protocol_version": GROUP, "group_id": "test/" + name,
            "revision": None, "name": name, "stages": stages})

    @staticmethod
    def stage(name="work", **updates):
        return dict({"stage_id": name, "executor_ref": CUSTOM, "spec": {}}, **updates)

    def execute(self, group, **options):
        return self.gym.experiments.execute(group["group_id"], revision=group["revision"], **options)

    def source(self, policy=ALL):
        return self.catalog.register_source({"protocol_version": DATA_SOURCE, "source_id": "test/public",
            "config": "default", "revision": None, "kind": "static",
            "provider_ref": {"name": "test.public-source", "version": "1.0.0", "origin_ref": None},
            "configuration": {}, "recipe": None, "reproducibility": {"mode": "snapshot", "seed": None},
            "usage_policy": copy.deepcopy(policy), "parent_datasets": [], "card_ref": None}, aliases=("release-1",))

    @staticmethod
    def source_ref(source):
        return {key: source[key] for key in ("source_id", "config", "revision")}

    def test_old_schema_definitions_are_unchanged(self):
        registry = SchemaRegistry()
        register_core_schemas(registry)
        self.assertEqual(F1_SCHEMAS, {name: digest(registry.resolve(name)).split(":", 1)[1] for name in F1_SCHEMAS})

    def test_resource_aliases_and_artifact_inputs_are_frozen_without_mutating_caller(self):
        source = self.source()
        data = self.catalog.register_snapshot([{"value": 3}], dataset_id="test/fixed", source_ref=self.source_ref(source), aliases=("release-1",))
        artifact = self.gym.artifacts.save_json({"value": 9}, "gymts.json/1")
        stage = self.stage(inputs={"dataset": {"kind": "dataset", "ref": {"dataset_id": data["dataset_id"],
            "config": "default", "revision": "release-1", "split": "test"}},
            "source": {"kind": "source", "ref": dict(self.source_ref(source), revision="release-1")},
            "asset": {"kind": "artifact", "ref": artifact}},
            bindings={"asset": "/actual"}, spec={"actual": None})
        original = copy.deepcopy(stage)
        group = self.register([stage])
        self.assertEqual(original, stage)
        frozen = group["stages"][0]["inputs"]
        self.assertEqual(data["revision"], frozen["dataset"]["ref"]["revision"])
        self.assertEqual(source["revision"], frozen["source"]["ref"]["revision"])
        self.gym.experiments.register_executor(CUSTOM, lambda spec, gym: {"actual": spec["actual"]})
        view = self.execute(group)
        self.assertEqual("succeeded", view["status"])
        request = self.gym.artifacts.read_json(view["attempts"][0]["request_ref"])
        self.assertEqual(artifact, request["inputs"]["asset"])
        self.assertEqual(artifact, request["spec"]["actual"])
        self.assertEqual(group, self.gym.experiments.get(group["group_id"], revision=group["revision"]))
        self.assertEqual(1, len(self.gym.experiments.query(dataset_id=data["dataset_id"], dataset_revision=data["revision"])))

    def test_failed_attempt_requires_explicit_retry_and_preserves_original_request(self):
        calls = []
        def executor(spec, gym):
            calls.append(copy.deepcopy(spec))
            if len(calls) == 1:
                raise ValueError("deliberate first attempt failure")
            return {"status": "succeeded", "answer": 4}
        self.gym.experiments.register_executor(CUSTOM, executor)
        group = self.register([self.stage(spec={"seed": 7}, outputs={"value": "/answer"})])
        failed = self.execute(group)
        first = copy.deepcopy(failed["attempts"][0])
        first_request = self.gym.artifacts.read_json(first["request_ref"])
        self.assertEqual("failed", failed["status"])
        self.assertEqual(1, len(self.execute(group)["attempts"]))
        completed = self.execute(group, retry_failed=True)
        self.assertEqual("succeeded", completed["status"])
        self.assertEqual(2, len(completed["attempts"]))
        self.assertEqual(first, completed["attempts"][0])
        self.assertEqual(first_request, self.gym.artifacts.read_json(first["request_ref"]))
        self.assertEqual([1, 2], [attempt["ordinal"] for attempt in completed["attempts"]])

    def test_rerun_propagates_staleness_without_rebinding_old_attempts(self):
        produced, consumed = [], []
        def executor(spec, gym):
            if spec["role"] == "produce":
                produced.append(len(produced) + 1)
                return {"value": produced[-1]}
            consumed.append(spec["bound"])
            return {"observed": spec["bound"]}
        self.gym.experiments.register_executor(CUSTOM, executor)
        group = self.register([self.stage("produce", spec={"role": "produce"}, outputs={"value": "/value"}),
            self.stage("consume", spec={"role": "consume", "bound": None},
                inputs={"upstream": {"kind": "stage_output", "stage_id": "produce", "output": "value"}},
                bindings={"upstream": "/bound"}, outputs={"observed": "/observed"})])
        initial = self.execute(group)
        previous = copy.deepcopy(initial["attempts"])
        old_requests = [self.gym.artifacts.read_json(attempt["request_ref"]) for attempt in previous]
        final = self.execute(group, rerun=("produce",))
        self.assertEqual("succeeded", final["status"])
        self.assertEqual([1, 2], consumed)
        self.assertEqual(4, len(final["attempts"]))
        self.assertEqual(previous, final["attempts"][:2])
        self.assertEqual(old_requests, [self.gym.artifacts.read_json(attempt["request_ref"]) for attempt in previous])
        self.assertEqual({"produce": final["attempts"][2]["attempt_id"]}, final["attempts"][3]["dependencies"])

    def test_run_and_organization_link_commit_in_the_same_transaction(self):
        group = self.register([self.stage()])
        store = self.gym.records.organization
        attempt = store.begin(group["group_id"], group["revision"], "work", {}, {})
        spec_ref = self.gym.artifacts.save_json({}, "gymts.json/1")
        real_link = store.link_run
        def fail_after_link(connection, context, run_id):
            real_link(connection, context, run_id)
            raise GymTSError("deliberate_failure", "Rollback after both insertions")
        before = copy.deepcopy(store.events(group["group_id"], group["revision"]))
        with store.scope(attempt), patch.object(store, "link_run", side_effect=fail_after_link):
            with self.assertRaises(GymTSError):
                self.gym.records.begin_run({"run_id": "rollback-run", "resolved_spec_ref": spec_ref})
        self.assertEqual([], self.gym.records.list_runs())
        self.assertEqual(before, store.events(group["group_id"], group["revision"]))
        with store.scope(attempt):
            self.gym.records.begin_run({"run_id": "committed-run", "resolved_spec_ref": spec_ref})
        linked = self.gym.records.list_runs(attempt_id=attempt["attempt_id"])
        self.assertEqual(["committed-run"], [run["run_id"] for run in linked])
        self.assertEqual(attempt["attempt_id"], linked[0]["organization"]["attempt_id"])

    def interrupted_child(self, *, evaluation=False):
        """Kill only a child owned by this test, after actual builtin executions."""
        self.gym.close()
        source = '''
import json, os, sys
from pathlib import Path
from gymts import GymTS
root, fixtures, evaluation = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == 'yes'
with GymTS(root/'store', data_home=root/'data', cache_home=root/'cache') as gym:
    spec=json.loads((fixtures/('forecast_evaluation.json' if evaluation else 'forecast_experiment.json')).read_text())
    executor={'name':'gymts.evaluate' if evaluation else 'gymts.run','version':'1.0.0','origin_ref':None}
    group=gym.experiments.register({'group_id':'test/interruption','name':'actual interruption','stages':[
        {'stage_id':'work','executor_ref':executor,'spec':spec,'outputs':{} if evaluation else {'result':'/result_ref'}}]})
    (root/'definition.json').write_text(json.dumps(group))
    original=gym.records.end_run
    def interrupt(run_id, result):
        if evaluation:
            if len(gym.records.list_runs()) == 2:
                os._exit(74)
            return original(run_id, result)
        original(run_id,result)
        os._exit(74)
    gym.records.end_run=interrupt
    gym.experiments.execute(group['group_id'],revision=group['revision'])
raise AssertionError('The hard interruption hook was not reached')
'''
        try:
            result = subprocess.run([sys.executable, "-B", "-c", source, str(self.directory), str(ROOT / "examples"),
                                     "yes" if evaluation else "no"], cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(74, result.returncode, result.stdout + result.stderr)
        finally:
            self.gym = GymTS(self.directory / "store", data_home=self.directory / "data", cache_home=self.directory / "cache")
        return json.loads((self.directory / "definition.json").read_text())

    def test_hard_interrupt_after_seal_can_adopt_without_rerunning(self):
        group = self.interrupted_child()
        view = self.gym.experiments.inspect(group["group_id"], revision=group["revision"])
        self.assertEqual("running", view["status"])
        self.assertEqual(1, len(view["runs"]))
        self.assertEqual("succeeded", view["runs"][0]["status"])
        run_id = view["runs"][0]["run_id"]
        original = copy.deepcopy(self.gym.records.get_run(run_id))
        with patch.object(self.gym.environment_ts, "run", side_effect=AssertionError("No reexecution during recovery")):
            with self.assertRaises(GymTSError):
                self.execute(group)
            restored = self.gym.experiments.recover(view["attempts"][0]["attempt_id"], reason="Child has exited; sealed Run verified", adopt_run=True)
            self.assertEqual("succeeded", restored["status"])
            self.assertEqual("succeeded", self.execute(group)["status"])
        self.assertEqual(original, self.gym.records.get_run(run_id))

    def test_hard_interrupt_mid_evaluation_exposes_all_opened_runs_and_does_not_resend(self):
        group = self.interrupted_child(evaluation=True)
        view = self.gym.experiments.inspect(group["group_id"], revision=group["revision"])
        self.assertEqual(2, len(view["runs"]))
        self.assertEqual(["succeeded", "running"], [run["status"] for run in view["runs"]])
        attempt = view["attempts"][0]
        self.assertEqual(2, len(self.gym.records.list_runs(attempt_id=attempt["attempt_id"])))
        before = copy.deepcopy([self.gym.records.get_run(run["run_id"]) for run in view["runs"]])
        with patch.object(self.gym.autobench, "evaluate", side_effect=AssertionError("Do not resend interrupted matrix")):
            with self.assertRaises(GymTSError):
                self.execute(group)
            with self.assertRaises(GymTSError):
                self.gym.experiments.recover(attempt["attempt_id"], reason="Matrix is not a single Run", adopt_run=True)
            self.gym.experiments.recover(attempt["attempt_id"], reason="Owned child exited; explicit inspection required")
            after = self.execute(group)
            self.assertEqual(1, len(after["attempts"]))
            self.assertEqual("interrupted", after["attempts"][0]["status"])
        self.assertEqual(before, [self.gym.records.get_run(run["run_id"]) for run in view["runs"]])

    def test_nonterminal_executor_result_is_not_a_successful_stage(self):
        self.gym.experiments.register_executor(CUSTOM, lambda spec, gym: {"status": "running", "partial": True})
        group = self.register([self.stage()])
        result = self.execute(group)
        self.assertEqual("failed", result["status"])
        self.assertEqual("failed", result["attempts"][0]["status"])

    def test_evaluation_only_source_cannot_reach_training_executor(self):
        source = self.source(EVAL_ONLY)
        calls = []
        self.gym.experiments.register_executor(CUSTOM, lambda spec, gym: calls.append(spec) or {})
        stage = self.stage(purpose="training", inputs={"source": {"kind": "source", "ref": self.source_ref(source)}})
        try:
            group = self.register([stage])
        except GymTSError as error:
            self.assertEqual("permission_denied", error.code)
        else:
            view = self.execute(group)
            self.assertEqual("failed", view["status"])
        self.assertEqual([], calls)

    def test_stage_output_dataset_policy_is_checked_before_downstream_executor(self):
        source = self.source(EVAL_ONLY)
        data = self.catalog.register_snapshot([{"public": 1}], dataset_id="test/heldout", source_ref=self.source_ref(source))
        calls = []
        def executor(spec, gym):
            calls.append(spec["role"])
            return {"dataset": {"dataset_id": data["dataset_id"], "config": "default", "revision": data["revision"], "split": "test"}}
        self.gym.experiments.register_executor(CUSTOM, executor)
        group = self.register([self.stage("publish", spec={"role": "publish"}, outputs={"dataset": "/dataset"}),
            self.stage("train", purpose="training", spec={"role": "train"},
                inputs={"heldout": {"kind": "stage_output", "stage_id": "publish", "output": "dataset"}})])
        result = self.execute(group)
        self.assertEqual(["publish"], calls)
        self.assertEqual("failed", result["attempts"][-1]["status"])
        self.assertEqual("permission_denied", result["attempts"][-1]["error"]["code"])


if __name__ == "__main__":
    unittest.main()
