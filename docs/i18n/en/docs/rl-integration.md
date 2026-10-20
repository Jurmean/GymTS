# Local RL rollouts and TRL GRPO

This integration ships as independent package `gymts-rl` under `adapters/rl/`, with source namespace `gymts_rl`. Data, tasks, models, private rewards, QA exporters, and the TRL backend belong to this adapter. The core retains the generic TraceCollector, training evidence contracts, and public build entry points from interface specification 1.2.0 without importing project adapters. Training reuses [TRL 0.18.2 GRPOTrainer](https://github.com/huggingface/trl/blob/v0.18.2/trl/trainer/grpo_trainer.py), including clipped GRPO loss, backward, optimizers, and checkpoints. GymTS provides native sampling, evidence, private rewards, fixed snapshots, and traceable datasets.

## Running directly on the current machine

An independent runtime exists at `/tmp/gymts-rl-venv/bin/python`. After migration, install the core and adapter there before running examples; other environments need the `runtime` extra below. Original models and Python environments were not modified.

```bash
/tmp/gymts-rl-venv/bin/python -m pip install -e . -e adapters/rl
```

Run from the project directory:

```bash
bash adapters/rl/examples/rl_grpo_local.sh
```

The script uses GPU 0, `/zzr/models/Qwen2.5-7B-I`, GSM8K, and the real ChatTS synthesizer to prepare data, perform three LoRA GRPO steps, infer held-out samples, and verify answers. Every invocation creates a new `/tmp/gymts-rl-时间戳`; results start at `training/training-summary.json`. Override the device, directory, model, steps, and interpreter through `CUDA_VISIBLE_DEVICES`, `GYMTS_RL_OUTPUT`, `GYMTS_RL_MODEL`, `GYMTS_RL_STEPS`, and `GYMTS_RL_PYTHON`.

Automatically generated heldout evaluation remains inference Runs and verifier diagnostics on samples independent of training; `evaluation_status=succeeded` means only that inference completed. Use the `score` command below or `score_rollout_runs` to produce an AutoBenchTS ScoreSpec and formal EvaluationReport for these sealed Runs, then rescore without model calls. Formal benchmark construction/maintenance and reports still belong to AutoBenchTS. Version 0.5 supports fixed checkpoint artifact loading and execution seed binding, as shown in the complete loop below. Training rewards or rollout.metrics do not replace formal reports, and Gates must be explicit. See [AutoBenchTS benchmark management](dataset-benchmark-catalog-design.md).

The first shard of `/zzr/models/Qwen2.5-7B-Instruct` is actually missing 82,746 bytes; use the shard-verified `Qwen2.5-7B-I`. `Qwen3-4B-Instruct-2507` lacks a complete checkpoint. Loaders check safetensors headers, shapes, dtypes, offsets, file lengths, and index references before hashing actual weights and custom code with SHA256.

Keep SQLite WAL, CAS, and training output on local POSIX storage such as `/tmp`. The current project directory resides on S3FS, suitable for source and sealed archives but not active SQLite. `/tmp` is runtime storage; persistent evidence requires separate archival.

## Step-by-step commands and native ChatTS

Run the following commands from the main source checkout. Put `--store` before subcommands, and use the same CAS for preparation and subsequent commands.

```bash
RL_PY=/tmp/gymts-rl-venv/bin/python
RL_OUT=/tmp/my-gymts-rl-experiment

"$RL_PY" -B -m gymts_rl.cli --store "$RL_OUT/records" prepare \
  --output "$RL_OUT/data" --gsm8k-train 128 --gsm8k-eval 32 \
  --chatts-train 32 --chatts-eval 8 --sequence-length 64

CUDA_VISIBLE_DEVICES=2 "$RL_PY" -B -m gymts_rl.cli --store "$RL_OUT/records" train \
  --data "$RL_OUT/data" --model /zzr/models/ChatTS-3-8B --family chatts \
  --trust-remote-code --device cuda:0 --dtype bfloat16 \
  --output "$RL_OUT/chatts-grpo" --steps 3 --generations 4 --groups-per-step 2 \
  --max-new-tokens 768
```

The `chatts` family uses the checkpoint’s own processor and time-series patch encoder, capturing the actual tensors supplied to the model. The `text` family replaces time-series placeholders with full-precision numeric JSON and records the transformation. Both share the same public questions and private verifier.

To sample without training, or consume a trained adapter in a new process:

```bash
CUDA_VISIBLE_DEVICES=2 "$RL_PY" -B -m gymts_rl.cli --store "$RL_OUT/records" rollout \
  --data "$RL_OUT/data" --model /zzr/models/ChatTS-3-8B --family chatts \
  --trust-remote-code --adapter "$RL_OUT/chatts-grpo/final-adapter" \
  --split eval --per-source 1 --generations 2 --max-new-tokens 768 \
  --output "$RL_OUT/reloaded-eval"
```

Training supports one process and one visible GPU only. If `CUDA_VISIBLE_DEVICES` is unset, the CLI makes the physical GPU chosen by `--device` the sole visible device before importing torch, preventing Trainer from enabling DataParallel. Python API callers must set the variable beforehand.

New environments can use Python 3.11 with `pip install -e . -e 'adapters/rl[runtime]'`. TRL, Transformers, PEFT, Accelerate, datasets, NumPy, Arrow, and pandas use fixed versions; default GymTS installation and `--help` do not import these scientific libraries. The existing runtime reuses read-only torch 2.11.0+cu126 packages and installs other dependencies independently; it does not reuse the vllm environment with flash-attn ABI issues. Inference uses local HF+SDPA without service credentials.

## Package boundaries and migration

Core distributions since 0.4 no longer provide `gymts.integrations.rl.*`; use `gymts_rl.*`. The 0.4.1 public build entry point is `gymts.training.build_dataset(spec, records, artifacts)`, selecting external providers by fixed builder_ref. Concrete `native_rollout_build_spec` and native row readers remain in `gymts_rl.exporter`. Its old two-argument helper `build_dataset(gym, spec)` remains compatible by delegating to the public entry point, without requiring a whole GymTS object as the provider contract. The core does not import RL back.

Adapter 0.2.0 depends on `gymts>=0.5,<0.6`; the old core `[rl]` extra moves to adapter `[runtime]`. ChatTS numeric generation comes from an explicitly selected upstream source directory and does not require the separate GymTS ChatTS adapter. Data/model identities, component/Schema/builder IDs, historical snapshots, and training algorithms retain their semantics. Python imports and distribution boundaries change.

## Three sides and experiment boundaries

| Side | Component | Behavior |
| --- | --- | --- |
| Data | `rl-qa-snapshot` | Immutable public prompt/array snapshots; private reference answers stored separately in CAS |
| Task | `rl-verifiable-qa` | One sample per case; parse format and preserve original text/evidence |
| Model | `rl-local-hf` | Artifact-loaded or legacy resident HF/ChatTS models; policy revisions frozen per Run, with updates controlled by external TRL |

After adapter installation, `rl = gymts_rl:register_rl_plugins` is discoverable through a `gymts.integrations` entry point; activate with `GymTS(root=..., integrations=("rl",))`. The default core contains neither this package nor its CLI, scientific libraries, or exporters. **One Run is one actual call for one sample × one fixed policy × one seed**; G generations of one question produce G independent Runs. Training is a parent record linking those Runs, batches, snapshots, rewards, datasets, and weight revisions. Optimizer updates occur between Runs rather than masquerading as Candidate online updates.

Each batch generates and seals Runs first; a trusted reward side then attaches Outcomes. Training Outcomes allow only `training_export`; evaluation Outcomes allow only `evaluation`. Candidate data access includes only that question’s public snapshot. Neither TaskInput nor training samplers contain answers, labels, or reward_spec.

## Data and rewards

GSM8K comes from the [official OpenAI repository](https://github.com/openai/grade-school-math), pinned to `3101c7d5072418e28b9008a6636bde82a006892c`, with SHA256 verification of both downloaded files. Official train has 7,473 rows and test 1,319; test is evaluation-only. Repeated rollouts preserve the same question group and are not deduplicated. Rewards verify a single final `#### number` line and compare correctness with Decimal: correct=1, otherwise=0.

ChatTS data comes directly from official numeric generation functions in `/zzr/scripts/ChatTS`, recording source commit, actual file hashes, configuration, dependencies, seeds, and attributes; AskGPT and external models are not called. The dataset is explicitly named **`chatts-native-generated/v1`**, with new task `chatts.numeric_summary`, not a reproduction of the seven-task ChatTS-Bench benchmark.

Time-series targets `mean/min/max/last` are calculated from real generated arrays. Models must return finite numeric JSON with exactly four keys. Invalid format scores 0, correct answers 1, and other answers `1 / (1 + MAE / scale)`. format_valid, correct, MAE, and reward are also reported independently. Train/eval use independent seeds and content-hash isolation checks. Metrics for the two sources are reported separately.

## Native trajectories and training consumption

Every real call saves:

- Formal ModelCallArtifact and run/input/output/call/attempt IDs.
- Real prompt/response token IDs including actual EOS, plus raw-model and actual-sampling logprobs.
- Actual generation configuration, seed, sampling distribution, stopping reason, usage, errors, and capture completeness.
- Exact tokenizer files and chat template; processor version and actual model tensor/mask inputs.
- Original NPY bytes, shapes, and dtypes for time-series tensors; bfloat16 is preserved losslessly as uint16 bit patterns.
- Actual base-weight/code content hashes, each frozen LoRA adapter file, and policy revision.

The core collector binds a preallocated output_id before invocation and immediately commits formal call events. Capture failures stop or mark according to configuration; storage failures always stop. Failed calls and invalid outputs retain available raw evidence. Default `model_calls=none` preserves existing behavior.

The training path is:

```text
sealed Run → authorized Outcome → RewardRecord → fixed RecordSnapshot
           → DatasetBuildSpec → native JSONL/CAS shards + lineage → DatasetManifest
           → TRL GRPO loss/backward/optimizer → saved adapter → new policy revision
```

`gymts.training.build_dataset(spec, records, artifacts)` uses external `NativeRolloutBuilder` to read only fixed sealed snapshots, verifying call identity, token hashes, policy, logprobs, label permission, and provenance. The Manifest is published last with accepted/excluded counts. Rows retain native IDs, old sampling logprobs, attention/action/loss masks, scalar rewards, and lineage references. EOS keeps action=1 even when sharing pad ID; prompt/padding have loss=0.


The public entry point validates only protocols, provider capabilities, and Manifest identity. `gymts.dataset_builders` entry-point names correspond to `builder_ref.name`; only the selected fixed provider is loaded. Missing/conflicting providers, versions, or target schemas fail explicitly. Profiles handle selection, authorization, segmentation, rewards, and masks. The core also checks consistency among the returned Manifest, complete CAS-stored BuildSpec, input snapshots, and output schema, and confirms output artifacts are committed.

```python
from gymts.training import build_dataset
from gymts_rl.exporter import native_rollout_build_spec

spec = native_rollout_build_spec(snapshot_refs, reward_refs, mapper_ref)
manifest = build_dataset(spec, gym.records, gym.artifacts)
```

`GymTSGRPOTrainer` continues reusing TRL loss/backward/optimizer without a new training engine. It now accepts `artifacts` and `rollout_provider(inputs, policy, *, generation, seed_start)` without GymTS or QA dataset configurations. Providers sample a new policy revision, publish fixed native DatasetManifests, and return `manifest_ref` and `batch_ref`. Trainer reads validated published shards and rejects differences from provider in-memory rows. It consumes standard `sample_id/source_sample_id`, policy_revision, native token/mask/logprob, and reward fields, not GSM8K/ChatTS configurations. Legacy `gym=..., prepared_dataset=...` remains compatible through a QA-provider closure.

```python
trainer = GymTSGRPOTrainer(
    policy=policy, args=grpo_args, train_dataset=public_prompts,
    artifacts=artifact_services, rollout_provider=collect_native_batch,
    peft_config=lora_config)
```

Only this native one-call/one-case profile is currently consumed. New sources may supply the same contract; multi-turn tool episodes or different action spaces need their own exporter/backend integrations rather than impersonating this QA profile.

TRL reads training inputs back from published shards instead of retokenizing decoded text. `row_indices` move with TRL shuffle so native tensors, logprobs, and rewards refer to the same generation. ChatTS forward expands time-series patches; current-policy logprobs align through model-returned `new_token_positions`.

This round supports one-call/one-case, native capture, and call-level scalar rewards. Truncated, missing, and failed calls are explicitly excluded with reasons preserved. GRPO stops if a group member is consequently missing and retains the whole batch, without fabricated samples/logprobs or missing rewards replaced by 0.

Training fixes T=1, top_p=1, top_k=0, beta=0, and one iteration, rejecting extra probability processors and verifying actual raw/sampling probabilities. HF `use_model_defaults=False` prevents checkpoint temperatures from overriding configuration. beta=0 means this flow has no reference KL term. Identical group rewards yield advantage 0. Short training proves executability, not quality improvement or a nonzero update at every step.

`training-summary.json` begins before initialization, updates per batch, and chains CAS revisions through `previous_summary_ref`. Construction failures, cancellation, and training exceptions retain parent links; nonfinite diagnostics are marked explicitly. Saved final checkpoints are reloaded through PEFT and checked against actual bytes, recording `weights_changed` and `checkpoint_reload_equal`. Held-out samples use separate eval Runs, but automatic diagnostics are still not formal reports. Fixed checkpoints can separately use AutoBenchTS.evaluate below.


## Complete loop from fixed artifacts to new experiments

After verifying every PEFT on-disk tensor against actual trained parameters, `run_training` publishes `checkpoint_bundle_ref`, `deployment_policy_revision`, and `training_provenance_ref` by default. One CAS ZIP contains adapter weights/config, tokenizer/processor bytes, and lineage to the training parent, actual DatasetManifest, RecordSnapshot, and sampling Runs. Publication revalidates references/final weights and compares the base directory against its fixed training-load identity, rejecting base files replaced during training. Deployment revisions fix base weights, adapter bytes/config, and input assets without depending on resident `active_policy`.

Large base models remain external and require explicit local paths matching complete file hashes. Small models may embed base weights through `include_base_in_bundle=True`, limited to 128 MiB. `load.base_model_path` relocates external models only when original content identity still matches; custom code requires explicit `trust_remote_code=True`. Loading checks ZIP paths, each file’s length/hash, policy identity, and actual PEFT tensor hashes. Embedded provenance canonical-JSON hash, length, and schema must match its original ArtifactRef; resaving after relocation preserves content identity. Candidates need authorization only for the entire archive, without recursively broadening CAS permissions.

```python
from gymts_rl.evaluation import checkpoint_evaluation_spec, rescore_checkpoint_evaluation

spec = checkpoint_evaluation_spec(
    gym, prepared, summary['checkpoint_bundle_ref'], heldout_sample_ids,
    seeds=[7, 11], generation={'max_new_tokens': 512},
    load={'device': 'cpu', 'dtype': 'float32'}, gates=explicit_gates)
report = gym.autobench.evaluate(spec)
rescored = rescore_checkpoint_evaluation(gym, report)
```

This helper constructs only native EvaluationSpecs: public questions and private evaluation-only references are published separately; AutoBenchTS still owns plan sealing, execution, comparison, Gates, and EvaluationReports. Runs sample from `CandidateContext.execution_seed` and record actual seeds; repetitions share one candidate/weight identity. Old explicit `params.seed` remains only for historical resident sampling, and new artifact Candidates reject it. `gym.validate` uses pure describe/compatibility without constructing data/task/model instances or reading models/data; content verification waits until runtime.

Run complete CPU engineering acceptance locally:

```bash
CUDA_VISIBLE_DEVICES= /tmp/gymts-rl-venv/bin/python -B \
  adapters/rl/examples/checkpoint_loop.py --output /tmp/new-gymts-checkpoint-loop
```

The example explicitly constructs a 1-layer Qwen2 engineering model with hidden=16, using real cached GSM8K and native ChatTS generation. To obtain effective within-group reward differences in its controlled vocabulary, training explicitly selects only official GSM8K train questions whose answer is 1. It reuses actual TRL GRPO entry points, loss, and optimizer, checking nonzero gradients, real weight changes without weight decay, and checkpoint reload equality. ChatTS numeric-summary data is really prepared and independently evaluated on holdout; this tiny model does not claim effective training improvement on that task.

Training and evaluation run in different processes. Original base-model/final-adapter paths are moved before evaluation, forcing CAS-archive assembly. Formal evaluation uses one GSM8K and one ChatTS question × three execution seeds; technical Gates require failure rate 0 and coverage 1, retaining actual accuracy without claiming model-quality success. A complete evaluation repeats the same seeds to verify sampling token-hash reproducibility, then blocks model loading/generation and rescores sealed Runs, checking unchanged results/events. The five user-uploaded benchmarks participate in neither training nor fixture selection.

Final independent-installation acceptance appears in [JSON evidence](reports/rl-checkpoint-loop-2026-10-20.json). With the fixed core 0.5.0 wheel and adapter 0.2.0 independently rebuilt/installed from sdist, 87/87 tests passed including real-source checks. Two actual GRPO updates had grad_norm 0.5753 and 0.6844 with weight_decay 0; weight hashes changed and reloaded identically. Complete records contain 28 sealed Runs: 16 training samples + 6 new evaluations + 6 repeated same-seed evaluations. All three formal evaluation/repetition/rescoring reports are in CAS; rescoring added no model calls and changed no original Runs.

Raw logs remain local at `docs/reports/rl-checkpoint-loop-2026-10-20.log` and do not ship with source. Local log paths or hashes in JSON identify original validation evidence, not repository downloads.

Formal accuracy was **0.0**, format_valid **0.5**, and scoring coverage **1.0**. Technical Gates establish an executable loop and complete evidence only, not model-quality success. Full acceptance covers the embedded tiny base model; external large bases and native ChatTS processors were not retrained/reaccepted here. Complete SQLite/CAS, inputs/checkpoints, exact wheels/sdists, and logs are separately archived at `output/rl-checkpoint-loop-resource-final-2026-10-20/full-evidence.tar.gz`, with SHA256 in JSON. Earlier candidates remain separate and do not replace the final round.

## Independent evaluation of old Runs

```bash
gymts-rl --store /tmp/my-gymts-rl-experiment/records score \
  --run-id <已有eval-run-id> --min-accuracy 0.8 \
  --output /tmp/my-gymts-rl-experiment/autobench-report.json
```

Repeat `--run-id` for multiple Runs. The command reads only sealed eval Runs, fixed outputs, and authorized evaluation Outcomes, returning native AutoBenchTS EvaluationReports and CAS references without loading models or training. Omitting `--min-accuracy` sets no acceptance Gate and retains `no_acceptance_gate`, not automatic pass. Python entry point: `gymts_rl.evaluation.score_rollout_runs(gym, run_ids, gates=...)`. `previous_evaluation_id` links rescoring; select new reference revisions explicitly through `outcome_refs=[{"outcome_id": ..., "revision": ...}]` rather than overwriting/mixing old references by default.

Independent `rl-qa-scorer` provides accuracy and format_valid. Format errors with valid references score 0; missing references retain the missing denominator, invalid references remain invalid, and neither receives invented zero rewards. format_valid needs no labels. Training-only Outcomes and train Runs cannot be relabeled independent evaluation. Old seeds inside CandidateSpec.params retain distinct candidate identities according to real configurations and captured model revisions, rather than falsely merging seeds into one candidate’s repetitions. New configurations place seeds in execution and load fixed checkpoints through CandidateSpec.artifact; old Run ScoreSpecs still evaluate only combinations actually executed.

verl currently has no trainer adapter; formal JSONL and native-input references remain available for later backends. Distributed execution, vLLM, importance correction for mixed temperatures, complex multi-turn tool episodes, optimizer-state training resumption, and Pi automatic Research loops are not implemented.
