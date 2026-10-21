# gymts-areal

Independent AReaL adapter for GymTS 0.5 / public contract 1.2. It connects the
**original AReaL TIR workflow and PPOTrainer** to sealed GymTS execution evidence.
The core contains no AReaL dependency. Registration and planning do not import
Torch, Transformers, SGLang, or the native training worker.

## Scope and stable responsibilities

- `gymts-rl` supplies replaceable public QA Source / Environment / Task / Scorer
  roles, pinned GSM8K preparation, and native ChatTS synthetic series.
- This package supplies `areal-live-tir`, a live native episode Candidate, the
  external coordinator, and `gymts.areal.sealed-tir-builder@2.0.0`.
- AReaL owns the calculator tool dispatch, native prompt/template/tokenizer,
  generation loop, sampled tokens/log probabilities, GRPO advantages, PPO loss,
  optimizer, LoRA parameters, weight transfer, and HF checkpoint saving.
- EnvironmentTS owns Run execution and immutable evidence. AutoBenchTS owns
  independent held-out evaluation and re-scoring.

This is a bounded engineering acceptance recipe: one original PPO update with
LoRA rank 16, one FSDP actor GPU plus one SGLang rollout GPU, policy staleness 0,
and calculator-only TIR. It does not claim a paper reproduction or improvement
on GSM8K. Full optimizer recovery, distributed multi-node training, other tools,
asynchronous stale-policy collection, and the AReaL v2 AgentWorkflow API are outside this recipe.
The native actor uses SDPA with exactly one episode per microbatch (checked at
runtime), avoiding cross-episode packed attention. Native SGLang uses its
`torch_native` attention/LoRA and `pytorch` sampling backends.

## Isolated installation

From a full GymTS source checkout, build the independent packages and the core
wheel. Paths below are examples; choose your own explicit working directory.

```bash
python -m build --wheel --outdir /tmp/gymts-wheels .
python -m build --wheel --outdir /tmp/gymts-wheels adapters/rl
python -m build --wheel --outdir /tmp/gymts-wheels adapters/areal
git clone https://github.com/inclusionAI/AReaL.git /tmp/areal-upstream
git -C /tmp/areal-upstream checkout 3b93679888e9f4929f6f155f13c6a286a62dfd72
cd /tmp/areal-upstream
uv sync --frozen --extra sglang
uv pip install --python .venv/bin/python --no-deps \
  /tmp/gymts-wheels/gymts-0.5.0-py3-none-any.whl \
  /tmp/gymts-wheels/gymts_rl-0.2.0-py3-none-any.whl \
  /tmp/gymts-wheels/gymts_areal-0.1.0-py3-none-any.whl
cd /tmp
/tmp/areal-upstream/.venv/bin/python -I -B -m gymts_areal.cli freeze-core \
  --wheel /tmp/gymts-wheels/gymts-0.5.0-py3-none-any.whl \
  --output /tmp/core-identity.json
```

`freeze-core` reads the supplied wheel and verifies every installed core file,
including its inventory, before writing an identity. It has no dependency on a
private local freeze file. Native workers check this identity again. Install
the same three wheels in any separate coordinator environment. Run from outside
the GymTS checkout with `-I`; no repository `PYTHONPATH` fallback is supported.
The worker prepends the explicitly chosen interpreter's `bin` directory to
`PATH`, because the original AReaL SGLang launcher invokes bare `python3`.
CPU preflight verifies that this native sub-launch selects the same environment.
Workers disable bytecode writes and put new runtime caches in the attempt's own
output directory. An already used native environment need not be overwritten:
install revised adapter wheels in a separate environment and keep the original
wheel, installed module hashes, logs and terminal parent for each attempt.

The fixed upstream lock uses explicit overrides in `pyproject.toml`, lines
235–244: OpenAI ≥2.8 despite SGLang's 2.6.1 pin; soundfile <0.13 despite its
0.13.1 pin; torchao 0.15 despite its 0.9 pin; cuDNN 9.19 despite Torch's 9.10
pin. Therefore `uv pip check` reports four conflicts in that native lock; this
adapter does **not** call it clean or silently replace the resolved environment.
Record the freeze, overrides, native imports and the actual GPU/model/kernel
preflight in each deployment. CPU import and CUDA matrix tests do not establish
SGLang or training compatibility by themselves.

## Prepare public data and private verifier references

Use an explicit local model directory, a clean pinned GSM8K source cache
(`3101c7d5072418e28b9008a6636bde82a006892c`), and an actual ChatTS checkout.
Preparation records source files, generator versions and exact generated values.
The five user-supplied benchmark files are evaluation-only and are not used here.

```bash
/tmp/areal-upstream/.venv/bin/python -I -B -m gymts_areal.cli prepare \
  --core-identity /tmp/core-identity.json --store /tmp/areal-demo/store \
  --output /tmp/areal-demo/data --gsm8k /path/to/pinned-gsm8k-cache \
  --chatts /path/to/ChatTS --train-per-source 4 --eval-per-source 2
/tmp/areal-upstream/.venv/bin/python -I -B -m gymts_areal.cli preflight \
  --core-identity /tmp/core-identity.json --store /tmp/areal-demo/store \
  --prepared /tmp/areal-demo/data/manifest.json --output /tmp/areal-demo/cpu \
  --upstream /tmp/areal-upstream --model /path/to/complete/local-model
```

The native trainer receives only exact public CAS samples through a map-style
Torch Dataset. It never reads the RL package's TRL JSONL exports, which contain
private `reward_spec` columns. No reference answer enters TaskInput, model
messages, or native workflow data. Native calculator execution sees only the
public current prompt. The adapter's declared prompt projection
`areal.public-calculator-verification@3.0.0` appends a public instruction to use
the calculator for relevant numeric verification. The model chooses its own
expression, tool call, reasoning and answer. The instruction documents only the
original tool's supported basic arithmetic (`+ - * /`, numbers and parentheses),
and excludes assignments, identifiers, functions and lists. Its arithmetic syntax
example is unrelated to the question and supplies no task calculation or reference answer. The immutable source sample
and the upstream system prompt remain unchanged; Candidate params, template
artifacts and capture transforms record this projection separately.
Training verification runs in the trusted coordinator;
the native workflow receives a scalar reward and its audit reference.

GSM8K test questions stay held out. ChatTS training/evaluation seeds and content
groups are disjoint. Answer CODEC 2.0.0 is explicit and gold-free:

- A last terminal `\boxed{...}` may have a closing LaTeX math delimiter and one
  terminal punctuation mark. Plain numeric contents become `#### ...`; boxed
  JSON contents must pass the existing numeric summary schema. A malformed or
  unsupported last box never falls back to an earlier answer.
- For a summary with no boxed answer, exactly one explicitly labeled Markdown
  `json` block may supply the answer object. Surrounding reasoning stays in the
  raw capture. Multiple blocks, concatenated JSON documents, duplicate keys,
  nested/non-numeric values and nonfinite values are rejected. The codec never
  scans arbitrary prose for numbers or chooses an answer using a reference.

The exact original native completion, canonical projected answer, rule name,
text hashes and CODEC reference are recorded separately. Native numeric values,
reference answers, verifier tolerance and scoring formulas are unchanged.
Training `format_valid` describes the canonical projected answer; it does not
claim that the raw native response was JSON-only or strictly formatted. The
independent HF evaluation below retains the existing QA parser and its own raw
output format semantics. Invalid canonical formatting is a legitimate zero
reward; verifier exceptions propagate as failures.

## Run the bounded original training loop

First allocate two idle GPUs and verify their physical index → UUID mapping.
Do not include GPUs used by others. This command requires both identities
explicitly and checks actual Torch-visible UUIDs before Trainer construction.
The adapter never changes the host driver or selects arbitrary available GPUs.

```bash
/tmp/areal-upstream/.venv/bin/python -I -B -m gymts_areal.cli train \
  --core-identity /tmp/core-identity.json --store /tmp/areal-demo/store \
  --prepared /tmp/areal-demo/data/manifest.json --output /tmp/areal-demo/train-1 \
  --upstream /tmp/areal-upstream --model /path/to/complete/local-model \
  --gpu-devices 0 2 --gpu-uuids GPU-YOUR-ACTOR-UUID GPU-YOUR-ROLLOUT-UUID \
  --seconds 3600 --episode-seconds 600 --group-size 4 \
  --max-model-requests 8 --max-new-tokens 512 --max-length 4096
```

Each native TIR episode joins one bound GymTS Run before its first model call.
Every actual native HTTP segment and tool attempt is persisted and ACKed before
the original native loop continues. Native retries are explicitly one physical
attempt, and each physical generation has a separate 180-second deadline.
`--max-model-requests 8` counts physical HTTP segments. Native TIR separately
generates tool-start and tool-end markers, so a tool call may consume two
segments, with a further segment needed to consume the result and answer.
The native `max_turns=2` behavior is preserved; the HTTP segment cap is recorded
separately from this native turn setting and the whole-episode time limit.
AReaL v1's `rollout.request_timeout` covers the whole remote group, including its
engine queue and bridge ACKs, rather than one HTTP request. The adapter sets it
to `group_size * episode_seconds + 120` (2520 seconds for the command above).
The coordinator's independent `--seconds` limit remains the total worker budget.
Native v1 groups normally use `gather`; an adapter episode lock provides
effective serialization (`serialize_group_samples` itself applies only to v2).
Native policy version 0 maps to exact base + initial LoRA files and cannot change
inside a Run. Each turn carries native token IDs, log probabilities, and policy
versions. Temperature 1, top-p 1, vocabulary-covering top-k and no frequency
penalty make the model/sampling distribution equivalent for the captured profile.

Before native TIR returns training tensors, the host validates reconstructed
prompt/model/tool token identity, model-only loss mask, finite log probabilities,
stable version, and the actual private verifier result. Native overlength or
length/abort termination is rejected: no full-answer reward is assigned to a
silently truncated sequence. Prompt and tool output tokens remain loss-mask 0.
An unconsumed final tool result is rejected as incomplete.

The Run is then sealed, a fixed RecordSnapshot is created, and the public builder
publishes a DatasetManifest with lineage, reward audit, tokenization profile and
the exact native tensor shard. Only tensors read back from that CAS shard are
returned to the original trainer, with hash and `torch.equal` checks. This is a
live training handoff, rather than an export created after optimization.

Builder 2 publishes `gymts.areal/native-tir-training-shard/2` with the recorded
CODEC 2 reference in rows and lineage, and in the fixed build specification's
transform declaration. The declaration says the syntax projection already ran
inside the live Run; the builder validates evidence and never reapplies a codec
or changes a reward. It rejects CODEC 1 evidence as a new profile. Retained old
V10 wheels provide the original Builder 1 / CODEC 1 profile when an old build
must be reproduced. Reading old evidence and scoring its already recorded
canonical outputs do not reinterpret them with CODEC 2.

The actor records which sealed row hashes it consumes, native advantages,
gradient norm, Adam step counters, trainable LoRA hashes and parameter deltas.
Weight decay is zero. All-zero advantages stop the attempt before an accepted
update; they are preserved and reported rather than converted into a fabricated
training success. Native HF saving is compared against the actual actor tensors
after the original saver's explicit key/dtype conversion. Failed and timed-out
Runs, partial attempts, budgets and parent summaries remain inspectable.
On Linux, the isolated worker binds its owned process group to the coordinator
with `PR_SET_PDEATHSIG`; normal native scheduler/RPC/SGLang subprocesses inherit
that group. Timeout, interrupt and parent-death checks target only that owned
group, never other jobs. A sudden host SIGKILL may leave an unsealed Run prefix;
it is retained as interrupted evidence, not claimed to be a completed Run.

## Load the trained checkpoint in a new process and evaluate

The native saver checkpoint is published into `gymts-rl`'s reusable immutable HF
deployment archive. Its lineage explicitly names AReaL, sealed native manifests,
and native optimizer/save evidence; no TRL training summary is invented.
Base weights remain at an explicit hash-verified locator. Tokenizer and LoRA
bytes are in CAS. A relocated machine must provide identical base model bytes.

The original native HF save is compared tensor-for-tensor against the actor's
actual native dtype/key conversion. Initial and final HF adapter tensor hashes
must differ. Original exported BF16 files, config and tokenizer assets are
preserved together in a separate CAS archive. For compatibility with PEFT's
default adapter loading behavior, deployment explicitly promotes exported
BF16/FP16 tensor values to FP32. Every tensor records its source/destination hash,
dtype, shape, exact promotion and exact round trip. This preserves the exported
values; it does not recover the optimizer's FP32 master precision or promise
bitwise-identical logits. No native checkpoint directory is rewritten.

`training_policy_revision` identifies the verified final native checkpoint and
observed final native version. `rollout_policy_revision` identifies the initial
policy used for sealed episodes. The deployment `policy_revision` separately
identifies the projected loadable archive; none of these identities is treated
as an adapter tensor hash or a fabricated native version increment.

The pinned HF5 tokenizer saver stores the complete ordered special-token list
under `extra_special_tokens`; HF4 expects that list under
`additional_special_tokens` and an optional named-token map under
`extra_special_tokens`. Publication defaults to `--tokenizer-compatibility native`
for the original metadata. Explicit `--tokenizer-compatibility hf4` produces a new
deployment revision with the complete ordered list moved to the HF4 field and an
empty named-token map. Conflicting lists, duplicate/non-string tokens and
unsupported field types are rejected. No token is removed or renumbered;
`tokenizer.json`, chat templates, adapter weights and other assets stay byte-identical.
The versioned tokenizer projection audit records source/destination config hashes,
the complete ordered list, preserved other fields and original checkpoint ref.
Actual vocab, token-ID, template and encode/decode equivalence must also be
validated in the intended runtime; the metadata helper's tests alone do not prove it.

To republish an existing completed native save for HF4 without rerunning training,
use a new output file and the original immutable training parent:

```bash
CUDA_VISIBLE_DEVICES= /tmp/areal-upstream/.venv/bin/python -I -B -m gymts_areal.cli publish \
  --core-identity /tmp/core-identity.json --store /tmp/areal-demo/store \
  --prepared /tmp/areal-demo/data/manifest.json \
  --training-parent /tmp/areal-demo/train-1/training-parent.json \
  --native /tmp/areal-demo/train-1/native-training-result.json \
  --model /path/to/complete/local-model --tokenizer-compatibility hf4 \
  --output /tmp/areal-demo/deployment-hf4.json
```

Publication checks the CAS parent, source manifest, sealed batch consumption,
nonzero advantage/update evidence, original saved tensors and policy map. It
cannot turn an incomplete native attempt into an accepted checkpoint. Earlier
bundle references remain immutable. Supply the new publication file to
`evaluate --bundle` when republishing.

Keep training and deployment evaluation in separate environments. The pinned
native lock uses Transformers 5.3.0; the reusable `gymts-rl` HF generation path
currently targets Transformers 4.57.6 (`generate(use_model_defaults=False)`).
Transformers 5 removed this argument: the retained first evaluation attempt
failed before producing an output, with four sealed failed Runs. Installing HF4
in a new inference environment avoids changing the original native training
runtime or the trained checkpoint. It does not promise bitwise-identical logits
between native training and deployment inference.

Create a dedicated evaluation environment, install a Torch build supported by
your GPU/driver, then install the following compatible HF package versions and
the same frozen core / RL / AReaL wheels. The local acceptance used Torch
2.9.1+cu129; CPU import checks alone do not prove a different CUDA build works.

```bash
python3.12 -m venv /tmp/areal-evaluation
/tmp/areal-evaluation/bin/python -m pip install torch==2.9.1
/tmp/areal-evaluation/bin/python -m pip install \
  transformers==4.57.6 huggingface-hub==0.36.2 peft==0.18.1 \
  accelerate==1.13.0 safetensors==0.7.0
/tmp/areal-evaluation/bin/python -m pip install --no-deps \
  /tmp/gymts-wheels/gymts-0.5.0-py3-none-any.whl \
  /tmp/gymts-wheels/gymts_rl-0.2.0-py3-none-any.whl \
  /tmp/gymts-wheels/gymts_areal-0.1.0-py3-none-any.whl
```

After the native actor and SGLang workers have closed, launch a **new process**:

```bash
CUDA_VISIBLE_DEVICES=0 /tmp/areal-evaluation/bin/python -I -B -m gymts_areal.cli evaluate \
  --core-identity /tmp/core-identity.json --store /tmp/areal-demo/store \
  --prepared /tmp/areal-demo/data/manifest.json \
  --bundle /tmp/areal-demo/deployment-hf4.json \
  --model /path/to/complete/local-model --device cuda:0 --dtype bfloat16 \
  --output /tmp/areal-demo/evaluation.json
python3.12 -m venv /tmp/areal-rescore
/tmp/areal-rescore/bin/python -m pip install --no-deps \
  /tmp/gymts-wheels/gymts-0.5.0-py3-none-any.whl \
  /tmp/gymts-wheels/gymts_rl-0.2.0-py3-none-any.whl \
  /tmp/gymts-wheels/gymts_areal-0.1.0-py3-none-any.whl
CUDA_VISIBLE_DEVICES= /tmp/areal-rescore/bin/python -I -B -m gymts_areal.cli rescore \
  --core-identity /tmp/core-identity.json --store /tmp/areal-demo/store \
  --report /tmp/areal-demo/evaluation.json --output /tmp/areal-demo/rescore.json
```

These commands declare no quality acceptance threshold. AutoBenchTS therefore
retains `verdict: insufficient_evidence`, `gate_results: []` and
`reasons: ["no_acceptance_gate"]` even when all Runs and metrics are complete.
The CLI checks engineering completion separately: every planned Run must
succeed, every metric must be ready with `0 < scored == eligible` and no
missing/invalid/excluded items, and no report error is allowed. Other insufficient
evidence reasons and failed quality gates still fail the command. A successful
command does not turn the report into a quality pass.

AutoBenchTS owns new evaluation Runs and independent outcomes. Evaluation reuses
the existing QA prompt and HF Candidate; it does not claim to measure the native
multi-turn tool policy. Re-scoring forbids both Candidate `prepare` methods and
checks that all execution records remain byte-identical. Keep the lightweight RL
adapter and Candidate manifests installed for re-scoring; native AReaL/SGLang
workers may be removed. Completely uninstalling an adapter preserves core/other
project use and evidence readability, not historical Candidate metadata resolution.

## Outputs and verification

The first local native acceptance attempt on 2026-10-21 failed while launching
SGLang: upstream's bare `python3` resolved to an unrelated Python 3.11 environment
beside the declared Python 3.12 worker. It consumed 458.65 GPU-seconds and
produced zero rollout Runs and zero optimizer updates. Its failed training-parent
record, native initialization log and verified initial LoRA save are retained.
The launch environment correction above is adapter-only; neither the frozen core
nor upstream source was changed. A subsequent attempt must link this failed
parent and retain its budget rather than resetting the experiment history.

The second attempt reached real native TIR generation but exposed the group
callback timeout mismatch described above. It was stopped, retained ten episode
Runs (nine succeeded and one failed), 15 model-call records, zero tool calls,
and no optimizer update. Its 1431.14 GPU-seconds were retained in the same budget.
The subsequent recipe changes both the group deadline and the versioned public
calculator instruction; no expression or answer is hardcoded. Acceptance still
requires actual model-selected successful calculator use and consumption of its
result, a nonzero native update, checkpoint reload and independent evaluation.
The third attempt demonstrated a successful real native calculator call but
also exposed the original four-segment HTTP cap: two tool-error recovery turns
required a fifth segment for the model to continue. It was stopped with nine
retained Runs (six succeeded and three failed), no optimizer update, and
1161.94 GPU-seconds. The revised recipe records an eight-segment cap and public
syntax projection 3.0.0, while preserving every earlier attempt and original
native tool implementation. A failed call is never relabeled as successful.
The fourth attempt sealed all 32 genuine native episodes but original CODEC 1
rejected their answer syntax, producing 32 legitimate recorded zero rewards.
The original trainer's nonzero-advantage gate rejected the batch before any
optimizer update. The attempt used 2166.88 GPU-seconds. A read-only diagnostic
with approved CODEC 2 found 22 parsable outputs and six groups with differing
counterfactual rewards; those diagnostic scores are not training data. Original
Run records, tensor rewards and failed parent remain unchanged. CODEC 2 requires
new live rollouts before any new native training attempt can be accepted.
The fifth attempt used new CODEC 2 live rollouts with the same public prompt
projection as the fourth attempt. All 32 real Runs succeeded; the original
trainer consumed exactly the same 32 sealed CAS rows. All 10,356 advantages were
finite and nonzero. One real optimizer update recorded gradient norm
0.0681703474, Adam step 0 → 1, 196 changed LoRA tensors and parameter delta L2
0.7870101283 with weight decay zero. Three original HF saves each matched 392
native-exported tensors; final saved weights differed from the initial save.
The attempt consumed 2470.16 GPU-seconds and published the original native BF16
archive plus the audited FP32 deployment. Its 104 physical model calls included
17 successful and four failed calculator attempts; every failure remains recorded.
Canonical projected formatting passed for 22/32 responses, whereas the raw
native strings passed the strict QA parser for 0/32. These training diagnostics
are not held-out quality results.

The first fresh-process evaluation retained four failed Runs and no generated
outputs: the original shared HF Candidate's `use_model_defaults` argument is
unsupported by HF5. It consumed 762.10 GPU-seconds. The separate HF4 environment
passed real tiny-model generation and checkpoint-loader tests, then exposed the
native tokenizer metadata incompatibility described above. An independent CPU
projection check preserved all 151,665 vocabulary entries and the complete ordered
13-token special list, special-token IDs, skip-special decoding, and three public
chat-template/input-ID/attention-mask examples. The original native checkpoint
and first deployment remain unchanged. The explicit HF4 deployment projection
is prepared and CPU-tested; actual republication, a new four-case evaluation and
model-free re-scoring remain pending the user's compatibility choice. No quality
acceptance threshold has been introduced.

CPU scripted workflow probes are identified separately and never counted as
real model episodes. Attempt-chain summaries use UTC/epoch times; original
native logs retain their local timezone.

- `native-config.yaml`, `resolved-native-config.json`: effective native config.
- `native-worker.log`: isolated native process output; no inherited credentials.
- `training-parent.json`: terminal status, policy map, every episode, sealed refs,
  actual consumed rows, advantages, optimizer and checkpoint evidence.
- `checkpoint-bundle.json`: immutable deployment bundle and AReaL provenance refs,
  including original native archive and tensor-level deployment projection refs.
- `evaluation.json` / `rescore.json`: independent AutoBenchTS reports.

`python -m unittest discover -s adapters/areal/tests` runs deterministic contract
tests; these are not a replacement for native GPU acceptance. Integration must
also pass wheel installation outside the checkout against the frozen core,
original multi-turn calculator use and subsequent result consumption, nonzero
advantages, real optimizer changes, checkpoint reload and independent re-scoring.
The native training artifacts above establish the bounded update; final held-out
engineering closure still requires the separately recorded successful evaluation
and model-free re-scoring artifacts.

## License

This adapter is [MIT licensed](LICENSE). AReaL is an independently installed
[Apache-2.0 project](https://github.com/inclusionAI/AReaL/blob/3b93679888e9f4929f6f155f13c6a286a62dfd72/LICENSE).
Upstream source, datasets, models and dependencies retain their own licenses;
this package does not vendor or relicense their algorithms or weights.
