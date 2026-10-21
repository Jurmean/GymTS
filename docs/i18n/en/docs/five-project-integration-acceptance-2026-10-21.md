# Five-project integration and acceptance record

Date: 2026-10-21. **Acceptance summary in progress**: this page distinguishes evidence already obtained from pending work. Preparation or contract tests do not establish native acceptance. The sealed Runs, Evaluations, Snapshots and project acceptance summaries are the final evidence.

Following the [five-project research proposal](five-project-integration-research-2026-10-20.md), this round selects TimeCopilot, ITFormer, Chronos-2, Data-Juicer and AReaL. It tests whether a frozen framework can support different workflows through independent adapter packages. The deliverable is the framework and its adaptation interfaces; these five projects do not become built-in core features. Responsibilities follow the [framework design](framework.md), [toolset boundary](agent-toolsets.md) and [project website](https://netman.aiops.org/contacts/projects/).

## F0 freeze and acceptance criteria

| Item | Fixed identity or rule |
| --- | --- |
| Main repository baseline | `121abca88b65094e899b294a3d3416ccd004a25d` |
| Core / public contract | GymTS `0.5.0` / `1.2.0` |
| This round's F0 wheel SHA-256 | `8883e708dbfcc46301939335f594884b40239ddd8bbe201a66e6af2f18e012cf` |
| Installed identity checks | 39 installed core files; verify actual import paths and file contents, without repository-source `PYTHONPATH` fallback |
| Core changes | 0 across all five executed project scopes, with all 39 core files matching F0; sixteen-package distribution and cross-project CPU replacements are verified; AReaL training/publication are complete, with held-out evaluation/rescoring pending |
| Resource boundary | The user approved at most 2 currently idle GPUs, serial experiments and 12 cumulative GPU hours; local models only, no paid APIs or system driver changes |

The core wheel is fixed while adapters, recipes, data projections and documentation can evolve independently. A core change is proposed only when an actual requirement cannot be expressed through existing public interfaces. Preserve a minimal failure, identify the extension points attempted, explain why the adapter is insufficient, and specify the new contract and compatibility with older projects. If core changes are necessary, produce F1, recheck older projects and test F1 through another independent new integration. Changing core for each project is not one frozen-core acceptance.

Each project separately requires installation from wheels/sdists outside source; real native execution; fixed data purposes and membership; complete success/failure evidence; actual parameter updates for selected training paths; independent AutoBench evaluation and zero-inference rescoring; and executable preparation, run and result-reading documentation. Mocks, successful imports, upstream unit tests and post-hoc trace imports do not replace this evidence.

## Responsibilities of the five adapters

| Layer | Stable responsibility | External implementation in this round |
| --- | --- | --- |
| EnvironmentTS | Authorized environment access, execution lifecycle, Runs, CAS, events and Snapshots | Adapters translate data sources, native harnesses and model/tool protocols |
| AutoBenchTS | Fixed evaluation plans, independent references, domain Scorer calls, comparisons and rescoring the same Run | Domain metrics, answer interpretation and quality boundaries remain external |
| Agents and toolsets | The Agent chooses an authorized tool and its arguments; tool returns inform subsequent decisions | Native TimeCopilot tools; LibraryTS and other collections remain optional external toolsets |
| Native training backends | Actual sampling, optimizer updates and checkpoints | Native Chronos `fit`; native AReaL rollout and optimizer, with acceptance recorded separately |
| Data processing | Fixed original/derived membership, lineage and quality evidence | Native Data-Juicer operators; explicit calls after execution decide data publication and purpose registration |

Toolsets are not built-in projects and do not require a new universal ToolBroker. TimeCopilot's internal cross-validation tools use authorized history only; independent future targets are unavailable to the Agent. Execution traces, training rewards, processing filters and formal evaluation are recorded separately. Candidates do not approve model deployment, data publication or training purposes themselves.

Replacing data, tasks or models depends on compatibility between their declared contracts. Shared time-series contracts can themselves live in external domain packages. AReaL is a training backend and Data-Juicer is processing infrastructure; they are not interchangeable with every forecasting Candidate.

## Current project status

| Project | Official source pin | Confirmed scope | Work remaining |
| --- | --- | --- | --- |
| [TimeCopilot](https://github.com/TimeCopilot/timecopilot/tree/961aa330f71afcf53a6ecf2d4b499cb39b44da3e) | `961aa330f71afcf53a6ecf2d4b499cb39b44da3e` | **Engineering loop completed**: local 14B, 6 model requests, all four native stages, Agent-selected AutoETS, independent future scoring and backend-forbidden rescore | No quality Gate; verdict is `insufficient_evidence`. Three earlier failures and budgets remain recorded; no forecasting advantage or paper reproduction is claimed |
| [ITFormer](https://github.com/OpenTSLab/ITFormer-ICML25/tree/b80142fc8b6ab2be8f148f3bb7a7534bb32f318b) | `b80142fc8b6ab2be8f148f3bb7a7534bb32f318b` | **Passed small-view engineering acceptance**: 8 QA, real model, independent scoring, rescoring without model dependencies, packaging and removal checks | Quality across all 42,477 test QA, training and paper reproduction are outside the verified scope |
| [Chronos-2](https://github.com/amazon-science/chronos-forecasting/tree/1224fafa91e1ecd6674f5204066b159e40b5e4a1) | `1224fafa91e1ecd6674f5204066b159e40b5e4a1` | **Engineering loop completed**: 16 baseline Runs, 60-step native training, heldout checkpoint evaluation in 16 new workers and zero-inference rescoring | No quality Gate was configured; verdict is `insufficient_evidence`, not a passed quality threshold or paper reproduction |
| [Data-Juicer](https://github.com/datajuicer/data-juicer/tree/abb9e49897bdd0e0e2f44ce3272cc1ea5c5a6111) | `abb9e49897bdd0e0e2f44ce3272cc1ea5c5a6111` | **Passed engineering acceptance**: native filter/dedup/QA, 12 model calls, independent quality, model-free rescore, explicit registration of 9 derived rows and fresh-process training-purpose reads | Generated labels remain unverified; no downstream training, quality improvement or paper reproduction is claimed |
| [AReaL](https://github.com/areal-project/AReaL/tree/3b93679888e9f4929f6f155f13c6a286a62dfd72) | `3b93679888e9f4929f6f155f13c6a286a62dfd72` | **Training/publication evidenced**: 32 real Runs, CAS tensor consumption, nonzero advantages, Adam update, native checkpoint and exact FP32 deployment projection | **Evaluation pending**: fresh-process held-out evaluation, model-free rescoring and sealed-hash checks await the final report; no claim of model improvement or paper reproduction |

Joint install/activation and removal regressions for sixteen packages, cross-project CPU replacement under declared compatible contracts, and two pre-native incompatible-combination rejections are verified within the scope below. The fifth AReaL recipe has real training and checkpoint-publication evidence. The first four failed/ineffective-update attempts remain recorded; fresh-process held-out evaluation and rescoring are pending. Each stage is assessed separately: CPU fixtures do not replace training, and sampling or tool success does not replace an optimizer update.

## Real TimeCopilot evidence obtained

The run uses real monthly AirPassengers data: the first 120 points are public history and the following 12 points are separate evaluation targets. Native `TimeCopilot.analyze`, its system prompt, tool closures, argument validators and output validator remain unchanged. The model chooses features, cross-validation models and the final forecaster. Enums are published only from native `TSFEATURES` and the actual forecaster registry; tool arguments and forecast answers are not scripted.

The successful experiment uses a complete local 14B checkpoint with content-tree SHA-256 `d0d6f379d2324a9748b6c5e45179102113f9887fb22e0872b0c9480556c6c935`. Following explicit user approval, the recipe selects `tool_choice_mode=auto`; the default remains `required`. Actual HTTP requests and session evidence record this policy. It is an explicit request-policy configuration, not a claim that the service rejects `required`, and it preserves the native output validator, all-four-tools requirement and final-model consistency checks.

| Metric or evidence | Actual result |
| --- | --- |
| Run | `run_654e248d308a48c9a1e7ca45ca802c78` |
| Independent future Evaluation | `evaluation_e06bc7e353c14b86ac8417b13229cee6` |
| First backend-forbidden rescore | `evaluation_6b91f9b88e9c46b192d451e5e357f455` |
| Fresh-process rescore after stopping the model service | `evaluation_a30df0bae04d4424a8fa1c4ae6bc4ad9` |
| Formal calls and budget | 6 successful HTTP ModelCalls, 4 successful native ToolCalls; provider usage totals 31,389 tokens, with no missing usage |
| Native tools | `tsfeatures_tool` → `cross_validation_tool` → `forecast_tool` → `detect_anomalies_tool`, once each |
| Agent selection | AutoETS; actual cross-validation compares at least two models including SeasonalNaive, and unchanged tool returns enter later model requests |
| Independent future MAE / RMSE | `44.41334215619239` / `52.018265022593305` |
| Formal counts and verdict | Both metrics have eligible=1, scored=1: one forecast unit containing 12 future points. `gates=[]`, so verdict is `insufficient_evidence` |

After stopping the local model service, a fresh interpreter explicitly forbids Popen, Candidate construction and native invoke. It imports no torch, TimeCopilot, PydanticAI or statsforecast. Every rescored metric is identical, and sealed result and event hashes remain unchanged. IO records contain actual requests, responses and tool returns but no native token IDs/logprobs; provider usage is not an RL rollout. Completing the engineering tool loop does not establish forecasting superiority or passing an unconfigured quality threshold.

All three earlier failures remain recorded: a 7B model chose unavailable feature `seasonality`; the 7B model with native enums repeated feature calls until the 12-tool cap; and the 14B model under `required` repeated the four stages until the same cap. Later success resets no historical budget and removes no failures. Late-outcome retries reuse immutable `available_at`, and original failed Runs have also completed model-free `score`; missing Runs remain in the planned denominator. All 13 CPU contract/lifecycle tests pass. Five use actual owned `sleep` processes to verify host termination, parent exit before guard setup and remaining-child cleanup, without model inference.

## Real ITFormer evidence obtained

### Official assets and derived data

The run uses [ITFormer-7B](https://huggingface.co/pandalin98/ITFormer-7B/tree/a5f52d265b7303bae513e77512453d86d477c44b) and external [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/tree/a09a35458c702b33eeacc393d103063234e8bc28). The lengths and SHA-256 hashes of all 11 actual shards match official pinned Hub LFS identities. Native base-Qwen loading reports no missing, unexpected or mismatched keys. All 150 non-LLM keys and loaded tensors were verified; random-encoder fallback was rejected.

[EngineMT-QA](https://huggingface.co/datasets/pandalin98/EngineMT-QA/tree/ea2051a15512212976c22c1a075ec549c7d48eef) is fixed at `ea2051a15512212976c22c1a075ec549c7d48eef`. The complete original HDF5 is 18,838,039,816 bytes, with `seq_data` shape `(118921, 600, 33)`. This round made 29 range reads totaling 3,328,912 bytes, producing a compact derived HDF5 of 21 real original signals. The whole original file was not downloaded.

The projection manifest records the official full-file LFS identity, actual byte ranges and hashes, original-value and native-float32 hashes, original-signal-ID to derived-row mapping, flattened QA indices and the new asset hash. It uses no zero-filled rows and does not label the projection as the complete original file. Fixed HTTPS provenance and range hashes are not a recomputation of the original whole-file LFS hash or a Merkle inclusion proof. The complete 17 MB QA file was checked against its official LFS SHA-256.

Selected flattened indices are `[0,1,2,3,4,11,12,35]`, two QA in each of four stages. Public signals/original questions are separate from evaluation-only answers. The native strict Dataset/Collator receives an empty-answer placeholder, and the model receives only five authorized input tensors, with no real labels/reference. Different QA are not deduplicated merely because they share a signal or source line.

### Execution and quality

| Metric or evidence | Actual result |
| --- | --- |
| Run | `run_00abb98bd1a3481ca5b34f1964c36e24` |
| First independent Evaluation | `evaluation_9aeab3ec4361429c9d01ef985d442517` |
| Zero-inference rescore using final release wheel | `evaluation_455cf0985af946f494d9a117fdde720f` |
| Actual model/tool calls | 8 successful ModelCalls, 0 ToolCalls; this model has no Agent tool behavior |
| Native token IDs | 672 prompt tokens, 144 completion tokens; no 128-token-limit truncation |
| Format validity | 8/8 |
| Mixed-task exact match | 2/8; Stage 2 is 2/2, Stage 3 is 0/2, and full-text exact match for open Stage 1/4 is 0/2 each |
| Lexical token F1 | `0.49763887682055463`; neither semantic correctness nor paper BLEU/ROUGE |
| GPU | One A800, 415.744 budgeted seconds, approximately 0.1155 GPU hours; no training |
| Original execution evidence | 62 events match the sealed execution Snapshot digest |

Engineering Gates check successful execution and scoring coverage of every fixed QA. A `pass` does not mean all questions were answered correctly, the model improved, or the paper was reproduced. The IO profile additionally retains real token IDs and input tensors but no logprobs; it is not claimed as a native RL training rollout.

### Independent rescoring and distribution

The wheel was rebuilt from its sdist and installed outside source. All 26 CPU contract tests pass, including source/answer separation, rejection of native pickle precedence, actual range boundaries, negative weight/shard checks, complete wheel identity checks against actual installed core bytes, wrong-hash rejection, and retention of the whole planned QA denominator on partial failure.

Tests are layered by optional dependencies. An environment with the `data` extra passes all 26 tests with zero skips. A core-plus-lightweight-adapter environment executes 21 tests and explicitly skips 5 HDF5/NumPy native-data CPU tests. Registration, schemas, core freezing, pure planning, real SDK scoring/rescoring and failed-result denominators still run in the minimal environment using clearly marked test-only JSON views. Skips do not establish data-preparation acceptance. All 12 production Python modules remain byte-identical to the previously validated wheel; this repair changes test layering and documentation only.

Rescoring succeeded in an independent interpreter without torch, transformers, h5py or timm. New Run execution and Candidate.prepare were explicitly forbidden and both counted 0; metrics matched the original evaluation. After removing the entire adapter, the core's 39 files still matched F0 and could read 8 historical results and 62 events. Domain scoring without the domain package is not claimed.

Both the executed wheel and final release wheel retain hashes. Final packaging adds one-command preparation, licensing/documentation, a preflight rejection of pickle overrides and pure-CPU portable core identity generation; native loading, preprocessing, generation and scoring algorithms were not replaced. The final wheel SHA-256 is `28cf434e3bb70b9db019a559c994aa83c69152d09deb12ff6e0e07af3d6b157b`. Rescoring used the final release wheel. Packaging changes did not trigger additional GPU validation.

## Real Chronos-2 evidence obtained

The profile uses fixed official ETTh1 data, history length 128, forecast length 24, two targets, historical variables and future calendar covariates verified against the time grid. Train `[0,8640)`, validation `[8640,11520)` and test `[11520,14400)` are separated chronologically. Final evaluation covers 16 fixed non-overlapping test windows. Future measured targets and sensor values are absent from public inputs.

Native training Run `run_508b298211354d21a174757c57f9bde3` records 60 requested steps, 60 optimizer updates and 60 gradient entries. All gradients and final weights are finite, some valid gradients are nonzero, `weight_decay=0`, and the before/after weight hashes differ. The immutable complete checkpoint archive SHA-256 is `d832567797c90493bed17286cdf816b1ed04bf73fbe76d1ecda6bf0a70140792`. Output within the training Run is diagnostic; formal post-training results come from independent checkpoint evaluation in 16 new workers.

| Metric | Baseline, 16 windows | Reloaded after training, 16 windows |
| --- | --- | --- |
| MAE | `1.1235232855` | `1.0884078331` |
| RMSE | `1.4479391914` | `1.3950889680` |
| pinball | `0.3647506867` | `0.3400679019` |
| 80% interval coverage | `0.6927083333` | `0.73046875` |
| Interval width | `2.7135988895` | `2.9040314918` |

Every metric scores 16/16 windows. The point prediction is native q=0.5, the median. Interpret coverage together with interval width. These are observed changes on a fixed small view; they do not establish population-level generalization improvement, and increased coverage alone does not establish calibration acceptance.

Post-training heldout Evaluation is `evaluation_334191dce7e24616beac8a3c08338657`. Rescoring without torch/chronos, with Worker and model identity calls forbidden, is `evaluation_4d99686833a743d5828c4efb4c350a67`. Sealed result and event hashes remain unchanged for all 16 Runs. Baseline zero-inference rescore is `evaluation_0dfcd60d61224c53be77150284e6d476`. Because the recipe has `gates=[]`, evaluation verdict is `insufficient_evidence`. Completed engineering evidence cannot be relabeled as passing an unconfigured quality threshold.

All 12 contract tests and the sdist rebuild check pass. Retained failures include the first Scorer list/dictionary boundary error, Run `run_17a39973b1c045e7b945d8bf004f971a` failing before fit because the training Payload was not unwrapped, and a retry conflict caused by changing an outcome's availability time. The latter two are addressed by an actual ArtifactStore regression and reuse of the immutable outcome revision. A pre-fit failure is not counted as completed training; neither budget nor failure records are deleted. This project changed no core code.

## Real Data-Juicer evidence obtained

The workflow uses pinned Data-Juicer `1.6.1` `init_configs`, `DefaultExecutor.run` and the native local HF QA mapper. ChatTS's own generator produces the inputs. Complete families are first split into 12 training families and 4 isolated holdout families; only the training inputs receive 2 duplicate records and 1 deliberately short record. Neither holdout nor user-supplied benchmarks reach the Candidate. The native worker uses isolated dependencies and local Qwen2.5-7B-Instruct, with no paid services or core changes.

| Metric or evidence | Actual result |
| --- | --- |
| Run | `run_f1b1d96a6c514a9986f41d343531bea5` |
| Independent Evaluation / model-free rescore | `evaluation_17905a0425034944a8fff1beeee62aac` / `evaluation_979a941b750a4294a188fd670142fc81`, both completed/pass |
| Native stages | 15 inputs → length filter 14 → exact document dedup 12 → QA output 9 |
| Formal calls | 3 operator ToolCalls, 12 real HF ModelCalls; every generation uses `return_full_text=False` |
| Source-level denominator | All 12 eligible sources: 6 correct, 3 numerically incorrect, 3 with no native QA output |
| Source accuracy / structure / coverage | `0.50` / `0.75` / `0.75` |
| Uniqueness / lineage / holdout isolation | All `1.0` |
| AutoBench counting level | One complete processing view is one evaluation unit; aggregate counts for all 6 metrics are eligible=1, scored=1, while quality diagnostics fix the 12-source denominator |
| Derived consumption | All 9 rows explicitly registered as `model_generated_unverified`; a fresh process reads 9 rows for training without native imports |

The auditing wrapper calls the original QA implementation and records real pipeline requests, returns and complete stage membership. The native mapper parses only new generated text, without treating the input format template as generated QA; full model IO is not rewritten. The independent Scorer recomputes numeric answers, structure, source coverage, remaining duplicates, complete stage lineage and holdout contamination. `pass` covers execution, lineage and purpose-isolation Gates only; accuracy of 0.50 does not establish that all answers are correct.

Rescoring completes in a lightweight environment without torch, explicitly forbidding Popen, Candidate.prepare and Source execution. All 6 metrics and counts match the original evaluation, and the Run remains unchanged. Derived registration requires an explicit caller action after successful Run sealing and a formal immutable quality report for the same Run. Failed lineage or holdout Gates reject training-purpose publication. The 3 incorrect answers remain unverified labels, without oracle filtering using independent answers; the 3 sources with no output remain in the scoring denominator. Successful reads do not establish downstream parameter updates or improved performance.

Four earlier failures remain recorded, including 12 real calls under the old prompt that generated only `Assistant:` and yielded zero parsed native QA. The final version strengthens public format instructions under a new source revision, without adding current answers or rewriting native output. Complete original traces remain local. The public small [machine-readable summary](../adapters/datajuicer/examples/native-validation-2026-10-21.json) contains no original questions, answers, models or active CAS.

## Real AReaL evidence obtained

### Native recipe and training

The independent adapter uses native TIR, calculator dispatch, GRPO advantages, PPOTrainer, LoRA parameters and HF saving. It changes no core files and does not substitute TRL for native training. Public samples come from pinned GSM8K train and train-only ChatTS synthetic views; independent test references do not enter prompts. The user-approved public projection `areal.public-calculator-verification@3.0.0` explains basic arithmetic syntax and verification, leaving expressions, tool calls and continuation to the model. All eight complete `native_messages` arrays have identical bytes in V10 and V11.

The recipe preserves native `max_turns=2`, with separate limits of eight physical HTTP segments, 180 seconds per segment, 600 seconds per episode and `4 * 600 + 120 = 2520` seconds per remote group. Tool start/end may occupy separate segments, with another model segment needed to consume the result. These limits are not tool counts. The fifth recipe collects new samples under new identities without rewriting earlier Run outputs or rewards.

| Training evidence | Actual fifth native-job result |
| --- | --- |
| Real sampling | 32/32 real native Runs succeeded; 17 successful native tool calls |
| Training input | The member Counter of all 32 original CAS tensor rows exactly matches actual consumption; not imported after optimization |
| Advantages | 10,356 nonzero finite advantage tokens |
| Gradient / optimizer | Gradient norm `0.0681703474`; Adam step `0 → 1`; `weight_decay=0` |
| Actual parameter changes | 196 LoRA parameter tensors changed; delta L2 `0.7870101283` |
| Native saving | Three HF saves, each with 392 tensors equal to actual parameters after the native explicit key/dtype cast; initial and final saved hashes differ |
| Native version | Final observed native policy version is `1`; adapter versions do not fabricate native increments |
| Pending results | Fresh-process held-out Evaluation, model-forbidden rescoring, their IDs and sealed result/event-hash checks are pending |

This is bounded engineering training with a real parameter update, not complete paper reproduction or evidence of improved test performance. The five projects are not all declared accepted before evaluation completes.

### Answer contract, checkpoints and distinct identities

`areal.boxed-to-verifiable-qa@2.0.0` projects syntax using only raw text and declared native stop tokens, never gold. It strips at most eight actually matching trailing stop tokens and reads the last complete terminal box, allowing only whitespace, one closing LaTeX delimiter and optional final punctuation afterward. GSM8K still requires a finite plain integer/decimal normalized to `#### <number>`; it evaluates no expressions and repairs no answers. ChatTS accepts boxed JSON, or exactly one explicit json fenced block only when the text has no boxed marker. A malformed final box cannot fall back to earlier answers. The original parser, four-field checks and numeric scoring are unchanged. Raw text/hash, projected hash, removed tokens and source format remain recorded; format rates explicitly concern the canonical projection.

Builder `gymts.areal.sealed-tir-builder@2.0.0` and `gymts.areal/native-tir-training-shard/2` require CODEC2 recorded during sampling and matching reward-audit identity. Their transform declares `already_applied_in_live_Run` and `reapply=False`; they reject retroactive CODEC2 application to CODEC1 evidence. The old contract still uses its original frozen builder.

Native BF16 checkpoint bytes remain in a separate CAS zip. Deployment creates a distinct FP32 projection, recording native/deployment dtype, shape and hash for all 392 tensors, with exact promotion and round-trip checks. Initial `rollout_policy_revision`, final native `training_policy_revision` and loadable deployment-bundle `policy_revision` remain distinct. Projection rewrites no native directory, restores no optimizer FP32 master precision and promises no bitwise-identical logits.

An independent tiny CPU publisher fixture loaded through the original `gymts_rl.checkpoint.load_checkpoint_policy` / PEFT, with the projected hash equal to the loaded tensor hash. Wrong saved hash, identical initial/final state, substituted consumption and absence of a successful fixture tool were rejected. Its synthetic bridge/FakeRecords are explicit test data with zero real Runs, tools or optimizer updates, not RL acceptance. V11 CPU testing with scientific dependencies separately completed 19/19 with zero skips; it does not replace real training either.

### Five attempts and preserved failures

| Attempt | Actual boundary and result |
| --- | --- |
| job1 | Upstream bare `python3` selected the wrong environment; zero rollouts and updates. Deployment PATH and native-child CPU preflight were subsequently corrected |
| job2 | A 180-second native remote-group limit timed out the group; failed/cancelled evidence remains sealed, with zero updates. Scripted CPU probes do not count as real training |
| job3 | Physical HTTP cap=4 blocked continuation after tool start/end; real tool successes and failures remain recorded, with zero updates |
| job4 | Under P3/cap8 all 32 real Runs succeeded, but all 32 original rewards were zero; the all-zero-advantages gate rejected the attempt, with zero updates |
| job5 | V11 collected new samples after user approval of CODEC2, obtaining the nonzero advantages, parameter update and checkpoint publication above; independent evaluation/rescoring are pending |

A read-only CODEC2 diagnostic of old job4 text found 22/32 parseable outputs and six groups with nonconstant counterfactual rewards. It is preflight only, with `diagnostic_only=true` and `used_for_training=false`. Original Runs, rewards, tensors and identities remain unchanged; counterfactual rewards are not completed training. The final attempt chain records precise denominators, budgets and artifact identities without deleting failures, resetting budgets or mixing in CPU fixtures.

### Failed held-out evaluation and pending compatibility projection

Native training uses Transformers `5.3.0`. The first fresh-process held-out evaluation, `evaluation_9c7daf8f6e014512b5bb07c19e5ee400`, fixes four expected units and records zero succeeded Runs and four failed Runs. The report itself is `completed` / `insufficient_evidence`; accuracy and format_valid aggregate counts are both eligible=4, scored=0 and excluded=4. The underlying cause of all four `capture_incomplete` errors is that HF5 no longer accepts the existing shared RL Candidate's `generate(use_model_defaults=...)` argument, not checkpoint loading or hash verification. The original report, failed Runs, model-call errors and host log remain preserved, without rewriting outputs, retraining or adding quality Gates afterward. This failed evaluation used `762.100938` GPU seconds. Closed allocations total `3.3442259951432547` GPU hours at this state, with no subsequent GPU evaluation yet.

A separate CLI issue incorrectly required engineering completion to have `verdict=pass`. V12 changes only the adapter CLI's completeness check: a complete evaluation without Gates may retain `insufficient_evidence`, while coverage, failures and errors are still checked. It cannot turn the four failed Runs above into successes and changes neither the Scorer, native training, model generation nor checkpoint contents. The executed V11 training and later CLI correction retain separate identities; byte equality of all final modules with the executed wheel is not claimed.

In an independent HF `4.57` environment, tiny CPU generation, teacher-forced log probabilities and the original shared RL loader passed preflight. Real production-asset preflight then correctly rejected the native HF5 tokenizer configuration: `extra_special_tokens` is an ordered list of **13** entries, whereas HF4 expects a named-token dict. This is not an empty-list conversion. The list is identical, in order, to the original base configuration's `additional_special_tokens`. The proposed versioned projection preserves all 13 entries in HF4 `additional_special_tokens`, uses an empty named map and preserves other configuration fields. Original `tokenizer.json` and chat-template bytes remain unchanged.

CPU checks on the real assets establish equality between the original HF5 tokenizer and proposed HF4 projection for all **151,665** vocabulary mappings, length, 13 special-token IDs, BOS/EOS/PAD, decoding, and three generic chat-template renderings, input IDs and attention masks. Report `v13-actual-tokenizer-metadata-cpu.json` also checks that the other four assets remain byte-identical. This establishes tokenizer equivalence, not new model inference or training, and does not promise bitwise-identical logits across HF runtimes.

The optional V13 publisher draft proposes explicit `--tokenizer-compatibility hf4` to create a new deployment asset. Native configuration remains the default; the original native archive, old bundle and sealed Runs remain unchanged. Draft checks discover 22 tests: 20 execute on CPU and two conditionally skip. **The user's compatibility-route choice remains pending; the draft has not published to the main store or run on GPUs, and no successful held-out evaluation or model-free rescore has been obtained.** V13 draft counts do not replace the recorded V2 + V11 distribution combination below. Tiny/metadata fixtures cannot establish successful production evaluation.

The successful training evidence has a separate durable **INTERIM** archive and passed restoration checks, rather than remaining only in a temporary directory while tokenizer choice is pending. Its ignored relative directory is `.gymts-five-projects/evidence/`; the complete receipt filename is `areal-before-tokenizer-choice-receipt-20261020T152725Z.json`, SHA-256 `71f0d1df91e6aa99a8979ed5cb4564ec9b96ceb48b752e8c03bb6a63f92f77ae`. The archive in the same directory is `areal-before-tokenizer-choice-evidence-20261020T152725Z.tar.gz`, 111,097,271 bytes, SHA-256 `b8a723381763bde32792766399705eec7acd70a1a0597457e9bd7d69c7471240`. These are local private archive locations on the deployment machine, not public download addresses, and do not replace the final master receipt.

Restoration verifies 92 sealed Runs: 83 train-purpose Runs (79 succeeded, four failed), five separate scripted CPU probes (three succeeded, two failed), and four held-out Runs (zero succeeded, four failed). These are neither 92 real training executions nor 83 parameter updates. All 1,398 events, 5,131 CAS refs and per-Run metadata/result/event hashes match original sealed traces; three prepared resource files for train=8 / eval=4 are recoverable. Validation uses lightweight CPU and all 39 F0 core files, with no model, scoring or GPU calls, and leaves the original SQLite/CAS unchanged. Tokenizer choice, successful held-out evaluation and rescoring remain pending.

## Cross-project replacement and distribution checks

The V2 sixteen-package frozen snapshot passes offline wheel/sdist builds, installation outside source, dependency resolution, joint activation and removal regressions. Its Python 3.11.8 report discovered 398 tests: 339 passed and 59 skipped. The recorded V11 total combines the other fifteen V2 packages with the independent V11 AReaL distribution supplement: replace the old AReaL subtotal of 13/13/0 with 19 discovered, 17 executed passes and two skips, giving **404 discovered, 343 executed passes and 61 conditional skips**. This is a combination of two identified frozen reports, not a claim that one complete check ran against all final source. V11 full-scientific CPU testing separately completed 19/19 with zero skips and is not added twice. V2 joint-activation and removal evidence remains intact: removing AReaL leaves the other fifteen packages and a core Run working. Conditional skips do not establish native model acceptance.

A separate host installs only F0 and the necessary lightweight wheels. It copies TimeCopilot's existing AirPassengers public snapshot without changing its CAS identity, 120-point history or independent 12-point future reference. Old LibraryTS native NaiveForecaster (drift) and PolynomialTrendForecaster (degree=1) replace the Candidate while reusing neutral timeseries Tasks/Scorers. Importing the same public values into `csv-numeric-snapshot` creates its own derived revision, but actual TaskInputs, forecasts and scores are identical across the two sources. The same public snapshot also supports a trend Task with a separately declared historical OLS-slope-sign reference; changing tasks is not called the same forecasting holdout.

| Task / Source | Candidate | Independent result |
| --- | --- | --- |
| forecast.numeric / one run each for snapshot and CSV | naive-drift | MAE `79.04341736694678`, RMSE `102.57890694158483` |
| forecast.numeric / one run each for snapshot and CSV | polynomial-linear | MAE `50.08248547352826`, RMSE `67.42081565543427` |
| pattern.trend_direction / original snapshot | One run for each Candidate | accuracy `1.0` for both; only one independent task unit per Candidate |

The result is 6 real CPU Runs, 6 native current-input fits, 6 formal ModelCalls and 6 internal ToolCalls, with 0 new LLM requests or GPU usage and no persistent weight training. Three independent scores are rescored in fresh processes with Popen, Candidates, Sources and native calls forbidden. Every metric, sealed result and event hash remains unchanged. Every original TimeCopilot store file retains its content hash; all work uses a separate store. Two incompatible combinations are rejected by real `gym.validate` and `gym.plan` with Popen forbidden: a Chronos distribution Candidate with the point-QA Task, and persistent `prepare=fit` for LibraryTS. Both rejections dispatch 0 processes.

Both the host and existing LibraryTS scientific interpreter verify all 39 core files against F0. No core or existing adapter production code changes. The old host wheel and native environment differ in wrapper bytes for `source.py/candidate.py/tools.py`, and their identities are retained separately. Executed worker/runtime bytes match, as do source-verification function ASTs; the source difference adds only scope/effect metadata. The old environment is not silently changed and whole-wrapper byte equality is not claimed. Two manifest/event-name assumptions in the evidence-reading script are retained in logs; recovery reads sealed results without rerunning completed native models.

The [machine-readable cross-project summary](reports/cross-project-role-replacement-2026-10-21.json) lists exact Runs, Evaluations, rescore IDs, counts and boundaries. All three evaluations retain `gates=[]` and `insufficient_evidence`. These checks establish the listed data, Task and Candidate replacements under compatible contracts. Fixed LibraryTS Candidates are not a new Agent loop, do not prove arbitrary external toolset replacement by TimeCopilot, and establish neither quality improvement nor paper reproduction.

## Failures and adapter corrections

| Actual issue or boundary | Handling and evidence | Core impact |
| --- | --- | --- |
| One local Qwen shard was short by 82,746 bytes | Rejected before loading; a complete read-only copy was used, then all 11 actual shards were checked against official LFS | 0 |
| The 18.8 GB HDF5 single-connection download was slow and incomplete | The incomplete file was not used; fixed official range reads produced an explicitly registered compact derived asset | 0 |
| Native ITFormer missing-weight/preprocessing fallback | Verify complete keys and actual tensors, enable strict preprocessing, check native tokens/signals and reject pickle-precedence overrides | 0 |
| TimeCopilot's tool schema omitted valid native choices | Publish enums from native feature/model registries, retaining closures and argument/output validators; preserve the invalid-feature failure | 0 |
| TimeCopilot did not terminate within the tool budget | Retain three real failures; explicitly user-approved `auto` configures a new experiment, preserving all-four-tools/final-model checks and historical budgets | 0 |
| An isolated worker may survive abrupt host termination | The adapter installs Linux parent-death protection and cleans only its owned session process group; five real-process regressions keep unrelated processes alive | 0 |
| Chronos record snapshots can be lists or wrapped dictionaries | Corrected in the external Scorer; finite gradients/weights, 60 actual updates and fresh-process checkpoint evaluation are verified | Core remains F0 |
| Chronos training views return a Payload | Explicitly unwrap it before reading authorized training fields; preserve the pre-fit failed Run and add an actual ArtifactStore regression | 0 |
| A retry changes availability time for the same outcome revision | Reuse the existing immutable outcome; reject changed references without rewriting old results or labels | 0 |
| Chronos calls its native return value mean but selects q=0.5 | Evidence and documentation explicitly identify the point prediction as the median, not a conditional mean | 0 |
| Upstream AReaL hardcodes `python3` and selects another local interpreter | The first job failed with zero rollouts/updates. Explicit PATH and native-child preflight were subsequently corrected; the first four attempts and job5 training remain separate without rewriting old evidence | 0 |
| Rescoring still needs the Candidate manifest | Retain lightweight registration metadata and domain Scorer while removing heavy native dependencies; this is an existing core 0.5 boundary | Core unchanged |

Subsequent failures must not be removed from coverage or budgets. Errors, cancellations, timeouts and unknown terminal states are retained alongside successes. A successful inference cannot replace failed training or invalid advantages. This page does not guess failure/retry counts that lack final reports.

## Usage entry points and storage

Use the actual package commands for preparation, installation, execution, checkpoints and rescoring:

- [TimeCopilot](../adapters/timecopilot/README.md): real Agent, AirPassengers history/hidden future, and model/tool budgets.
- [ITFormer](../adapters/itformer/README.md): official range projection, native model, independent answers and distribution outside source.
- [Chronos-2](../adapters/chronos/README.md): ETTh1 multivariate/calendar covariates, quantiles, native fit and checkpoints.
- [Data-Juicer](../adapters/datajuicer/README.md): ChatTS train-only processing, complete membership lineage and explicit derived-data registration.
- [AReaL](../adapters/areal/README.md): native TIR/PPO training, checkpoint publication and lightweight distribution are verified; fresh-process held-out evaluation and rescoring are pending.

ITFormer's fixed 8-QA view has been verified with one explicit preparation command:

```bash
gymts-itformer prepare-official --output /tmp/gymts-itformer/prepared
```

Preparation verifies the QA content and reads the required official signal ranges. Subsequent `--view` points to `/tmp/gymts-itformer/prepared/view`. A new real run still requires explicit native-checkout, model, base-Qwen and authorized-device configuration following the package README. This command alone does not establish model execution.

After building and installing the core wheel following the package README, users can generate the identity required by later commands without this round's temporary acceptance directory:

```bash
gymts-itformer freeze-core \
  --wheel /tmp/gymts-itformer-wheels/gymts-0.5.0-py3-none-any.whl \
  --output /tmp/gymts-itformer/core-identity.json
```

This command compares the actual imported complete installed package with the supplied wheel's original bytes, file by file, and records its version and wheel SHA-256. Editable/source fallback is rejected. The actual F0 wheel passed; an incorrect `--expected-sha256` fails without writing an identity. The generated file contains no absolute machine paths or historical Git requirement, and has been used for `plan` and rescoring without model dependencies. An identity for a locally rebuilt wheel does not establish this round's fixed F0 provenance; compare against the fixed wheel hash above when verifying F0.

Active SQLite/CAS, builds, checkpoints and worker directories use a local POSIX filesystem. Models, raw data and download caches are stored separately and excluded from Git. Public source contains interfaces, recipes, documentation and small summaries without private original questions/answers. Complete CAS, original/derived datasets, models, training outputs and large logs remain locally archived.

The complete ITFormer acceptance summary is `itformer/acceptance.json` within the runtime workspace; its Run store is `itformer/runs` in that workspace. These are local acceptance artifacts, not publicly downloadable benchmark or model releases. Identities and metrics in public documentation do not replace inspection of the complete CAS.

## Claims not made

This page does not claim all five projects have passed, arbitrary interchangeability of heterogeneous roles, or complete paper reproduction. TimeCopilot's real tool loop and independent rescore, sixteen-package distribution/removal regressions and the listed cross-project replacements are complete. AReaL has effective training and checkpoint-publication evidence; only fresh-process held-out evaluation and rescoring await the final report. Data-Juicer derived registration and actual reads are complete, while generated labels remain unverified. Chronos training/reload engineering evidence is complete, but no formal quality Gate was configured.

A trace is not a reward; independent scoring is not approval of training labels; successful processing does not establish generated-answer correctness. The user's five benchmark attachments remain evaluation-only. Code, data and model licensing are recorded separately. A trusted Python adapter is not an operating-system sandbox. Candidates do not decide model deployment, remote publication, resource expansion or core changes themselves.
