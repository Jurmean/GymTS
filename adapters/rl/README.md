# GymTS RL adapter

`gymts-rl` is an independently installed adapter for GymTS 0.5.x. It provides the
`rl-qa-snapshot` data adapter, `rl-verifiable-qa` task, `rl-local-hf` candidate,
GSM8K/ChatTS source preparation, native QA dataset exporter and TRL GRPO backend.
The GymTS framework does not depend on this package. Installing it makes its
`rl` entry point discoverable; registration and model execution remain explicit.

From a GymTS monorepo checkout:

```bash
python -m pip install . './adapters/rl[runtime]'
gymts-rl --help
bash adapters/rl/examples/rl_grpo_local.sh
```

For a wheel or standalone source archive, install its runtime extra using
`python -m pip install 'gymts-rl[runtime]'`, or the corresponding local wheel.
The base adapter installation needs only GymTS; imports, registration and
`--help` do not load torch, Transformers or TRL. The example additionally needs a
complete local model checkpoint, a versioned upstream ChatTS generator checkout
and access to the pinned official GSM8K source (or its verified local cache).
The ChatTS generator is invoked through its upstream public numerical functions;
this adapter does not depend on the separate `gymts-chatts` adapter.

```python
from gymts import GymTS
from gymts.training import build_dataset
from gymts_rl.exporter import native_rollout_build_spec, read_native_dataset_rows

with GymTS('/tmp/gymts-rl-records', integrations=('rl',)) as gym:
    # Build from fixed RecordSnapshot and authorized RewardRecord artifact refs.
    # spec = native_rollout_build_spec(snapshot_refs, reward_refs, mapper_ref)
    # manifest = build_dataset(spec, gym.records, gym.artifacts)
    pass
```

Public training evidence schemas and `build_dataset(spec, records, artifacts)`
remain in `gymts.training`. The concrete one-call/one-case QA provider lives in
`gymts_rl.exporter` and is selected through the `gymts.dataset_builders` entry
point. It receives records/artifacts rather than a GymTS orchestrator. The old
adapter helper `gymts_rl.exporter.build_dataset(gym, spec)` stays compatible;
the framework never imports that helper directly. Builder, mask,
component and schema identifiers and native sampling/training semantics are
unchanged, so this packaging change does not relabel historical artifacts.
Sealed Runs, input/output IDs, snapshots, rewards, masks and shard integrity
remain checked before an export is consumed.

Training and held-out verifier diagnostics do not constitute an AutoBenchTS
EvaluationReport. `gymts-rl score --run-id ... --output ...` now uses the independent
`rl-qa-scorer` and AutoBenchTS.score on sealed eval Runs, without loading a model.
Supply an explicit acceptance gate with `--min-accuracy`; absent gates do not
produce a pass. New training also publishes an immutable checkpoint archive:
exact PEFT adapter/config, tokenizer/processor assets, a fixed base identity and
training lineage through DatasetManifest, RecordSnapshot and source Runs.
Large bases use an explicit local locator verified against every committed file
hash; `include_base_in_bundle=True` embeds small bases (up to 128 MiB).
`CandidateSpec.artifact` loads this archive in a new process. Sampling comes from
the Run's execution seed; repeated seeds preserve one candidate identity.
Historical explicit candidate seeds retain their recorded identities.

```python
from gymts_rl.evaluation import checkpoint_evaluation_spec, rescore_checkpoint_evaluation

# summary = run_training(...)
# spec = checkpoint_evaluation_spec(gym, prepared,
#     summary['checkpoint_bundle_ref'], heldout_sample_ids,
#     seeds=[7, 11], gates=explicit_gates)
# report = gym.autobench.evaluate(spec)
# rescored = rescore_checkpoint_evaluation(gym, report)  # no inference
```

For a complete CPU engineering demonstration, use the packaged example:

```bash
CUDA_VISIBLE_DEVICES= python examples/checkpoint_loop.py --output /tmp/new-rl-checkpoint-loop
```

From the monorepo its path is `adapters/rl/examples/checkpoint_loop.py`. It needs
the runtime extra and the same real source caches/generator as preparation. It
constructs a declared tiny Qwen2 fixture, runs actual TRL GRPO with nonzero reward
variance and gradients, archives the checkpoint, removes the original model and
adapter paths, and evaluates from the artifact in a new process. One candidate,
two held-out cases (GSM8K and ChatTS), three seeds and zero-inference re-scoring
use native AutoBenchTS. Technical gates cover execution and scoring coverage;
actual task accuracy remains visible. This tiny model is an engineering fixture,
not a pretrained model or a benchmark quality claim. Only explicitly selected
GSM8K training examples drive this fixture's optimizer; ChatTS is prepared and
independently evaluated. The five uploaded benchmarks are never training inputs.

The existing TRL GRPO subclass accepts `artifacts` plus an injected
`rollout_provider(inputs, policy, *, generation, seed_start)`. The provider
publishes a native DatasetManifest and batch ref; the Trainer re-reads verified
shards and retains TRL loss/backward/optimizer. The old gym/prepared_dataset
constructor remains a QA recipe wrapper, while new sources can supply the same
native contract without GSM8K/ChatTS source configuration. Complex episodes need
a matching export profile/backend; this is not a new training engine.

Run the adapter's contract suite from its standalone source archive:

```bash
python -m unittest discover -s tests -v
```

The tests use explicit small fixtures. Optional native source checks require
`GYMTS_RL_NATIVE=1`; actual model training is not run by the normal suite.
See the repository's `docs/rl-integration.md` for local runtime, hardware and
experiment evidence details. Active SQLite/CAS and checkpoints need a local
POSIX filesystem, rather than an S3FS source checkout.

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
