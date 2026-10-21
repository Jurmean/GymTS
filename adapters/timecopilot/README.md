# GymTS TimeCopilot adapter

`gymts-timecopilot` connects the **native TimeCopilot Agent**, rather than a fixed forecasting baseline, to GymTS 0.5 / public contract 1.2. It is an independently installed and removable package. The GymTS core contains no TimeCopilot imports, model code or domain scoring logic.

| Responsibility | Implementation |
|---|---|
| Execution, CAS evidence and sealed Runs | GymTS EnvironmentTS |
| Static numeric history, forecast task, MAE/RMSE scorer | Independent `gymts-timeseries` package |
| Agent reasoning, feature selection, CV model selection, forecast and anomaly tools | [Native TimeCopilot](https://github.com/AzulGarza/timecopilot/tree/961aa330f71afcf53a6ecf2d4b499cb39b44da3e), release 0.0.38 |
| Independent future-point scoring and model-free rescore | GymTS AutoBenchTS with the neutral scorer |
| Native process isolation and model/tool evidence mapping | This package |

Supported Candidate: `timecopilot-agent@1.0.0`. Supported task: `forecast.numeric` versions `0.1.0` and `0.2.0` over `gymts.task/timeseries-qa/1`. It accepts one finite, univariate history with explicit `context.start`, `freq`, `seasonality` and `horizon`. Model and algorithm identities are fixed. Persistent training, inherited weights, online updates and `native_rollout` token/logprob capture are unsupported.

## Native behavior and evidence

The adapter calls native `TimeCopilot.analyze`, with its original system prompt, output validator and native tools. The upstream prompt requires four stages: `tsfeatures_tool`, `cross_validation_tool`, `forecast_tool`, `detect_anomalies_tool`. The LLM chooses feature names, the CV model list, and the final forecast/anomaly model. Available CPU models are native `AutoETS`, `AutoARIMA` and `SeasonalNaive`; the upstream implementation always makes its seasonal baseline available. Tools fit only the currently authorized history, including CV splits inside that history. They receive no independent future targets.

The adapter uses PydanticAI's public `Agent.toolsets`, `Agent.override` and `WrapperToolset` APIs to observe the original tool closures. It does not replace their algorithms or impose a scripted tool conversation. A transparent HTTP transport records the actual OpenAI-compatible model request and response, including tool schemas, tool-call IDs, arguments and subsequent tool-result messages. Authorization headers and credential values are excluded. Public model/tool evidence is recorded during `Candidate.infer`, bound by the Runner to the active Run/input/output. No universal ToolBroker or new core role is introduced.

The fixed native prompt lists valid features in prose, while its tool schema accepts arbitrary strings. In the first real run the LLM twice selected the unavailable feature `seasonality`; that Run remains failed. This adapter publishes enums from the actual native `TSFEATURES` registry and the configured native forecaster aliases in the tool schemas, using public dataclass copies. Original closures, argument validators, feature computations and model selection remain native. The LLM still chooses the features and models. Model requests capture these exact schemas, and the successful session records this compatibility transform. No answers or evaluation-only future values are added.

Worker events use an ordered JSON-lines protocol. The host saves each event and acknowledges it before the worker continues. Model/tool attempts receive terminal evidence, and an interrupted active invocation remains `unknown`, with its saved request. A session artifact links native events, formal calls, identities, final native frames, full native messages, budget counters and success/failure. Native pandas frame JSON converts non-finite cells to `null`, explicitly recorded as a serialization transform; exact native textual tool returns remain in the tool evidence.

The upstream `is_better_than_seasonal_naive` field is the Agent's own statement and validator input. It is **not** the independent evaluation result. MAE/RMSE are computed against withheld future observations by the neutral scorer after execution has sealed the Run. A successful demo proves the engineering loop, not forecasting superiority or a paper reproduction.

## Install the independent packages

Use a complete source checkout to build the optional packages. The core wheel does not contain these adapter sources.

```bash
python -m build --wheel adapters/timeseries --outdir /tmp/gymts-timecopilot-wheels
python -m build adapters/timecopilot --outdir /tmp/gymts-timecopilot-wheels
python -m venv /tmp/gymts-timecopilot-host
/tmp/gymts-timecopilot-host/bin/python -m pip install \
  /path/to/frozen/gymts-0.5.0-py3-none-any.whl \
  /tmp/gymts-timecopilot-wheels/gymts_timeseries-0.2.0-py3-none-any.whl \
  /tmp/gymts-timecopilot-wheels/gymts_timecopilot-0.1.0-py3-none-any.whl
```

Neither installation nor integration discovery loads the native scientific stack, opens the checkout, connects to a model, or starts training. Planning is JSON-only. Use an isolated native interpreter for the heavy upstream dependencies. Python 3.10 avoids upstream's Python >=3.11 `mlstm-kernels` dependency and explicit torch 2.10 constraint; this CPU path requires no GPU or driver changes.

```bash
git clone https://github.com/AzulGarza/timecopilot /tmp/native-timecopilot
git -C /tmp/native-timecopilot checkout 961aa330f71afcf53a6ecf2d4b499cb39b44da3e
uv venv --python 3.10 /tmp/gymts-timecopilot-native
uv export --project /tmp/native-timecopilot --frozen --no-dev --no-emit-project \
  --no-hashes --format requirements-txt --output-file /tmp/timecopilot-upstream-constraints.txt
uv pip install --python /tmp/gymts-timecopilot-native/bin/python --torch-backend cpu \
  --constraint /tmp/timecopilot-upstream-constraints.txt /tmp/native-timecopilot
uv pip install --python /tmp/gymts-timecopilot-native/bin/python \
  /path/to/frozen/gymts-0.5.0-py3-none-any.whl \
  /tmp/gymts-timecopilot-wheels/gymts_timeseries-0.2.0-py3-none-any.whl \
  /tmp/gymts-timecopilot-wheels/gymts_timecopilot-0.1.0-py3-none-any.whl
```

The constraints export is used as constraints, not as `pip install -r`: it also lists dependencies for upstream optional features. Capture the actual environment with `uv pip freeze --python /tmp/gymts-timecopilot-native/bin/python`. This wrapper package does not redistribute upstream source, forecasting libraries, datasets, or weights. During prepare, the adapter checks the clean checkout revision and verifies every installed TimeCopilot `.py` file against that checkout. Worker processes run from a fresh external directory using `python -I`, without repository `PYTHONPATH`, with CUDA hidden and CPU thread limits set.

## Prepare data and configuration

Write `implementation.json` outside the repository:

```json
{"repository":"/tmp/native-timecopilot","python":"/tmp/gymts-timecopilot-native/bin/python","revision":"961aa330f71afcf53a6ecf2d4b499cb39b44da3e"}
```

Write `params.json` with a model endpoint you own and an immutable checkpoint/content identity. This example uses a local service; it does not start that service or authorize paid APIs.

```json
{
  "implementation":{"repository":"/tmp/native-timecopilot","python":"/tmp/gymts-timecopilot-native/bin/python","revision":"961aa330f71afcf53a6ecf2d4b499cb39b44da3e"},
  "model":{"base_url":"http://127.0.0.1:8000/v1","name":"local-qwen3-4b","revision":"REPLACE_WITH_FIXED_CHECKPOINT_DIGEST","tool_choice_mode":"required"},
  "forecasters":["AutoETS","AutoARIMA","SeasonalNaive"],
  "limits":{"max_requests":16,"max_total_tokens":120000,"max_response_tokens":4096,"max_tool_calls":12,"max_wall_time_s":600},
  "temperature":0,"retries":2
}
```

The service must implement non-streaming OpenAI `/chat/completions`, function `tools`/`tool_calls`, tool-result messages, and truthful `usage.total_tokens`. Native structured final output also uses a function tool. Set `model.credential_env` only if authentication is needed; it is an environment-variable **name**, never a secret. Credentials are passed only to the native worker. Provider sampling enforcement is recorded as unverified; no reproducible native token/logprob claim is made.

`model.tool_choice_mode` explicitly selects `required` (the default) or `auto`. The adapter maps this choice to PydanticAI's `OpenAIModelProfile(openai_supports_tool_choice_required=...)`; actual model requests and the session's `provider_request_policy` record the resulting policy. Set `"tool_choice_mode":"auto"` only as a deliberate recipe choice. This does not assert that the service rejects `required`, alter native tools or output validators, prescribe tool arguments, or relax the requirement for all four successful native stages and consistent final model/forecast. A new run under `auto` is a separate experiment; configuration support does not establish successful Agent acceptance.

Requests and tool executions have strict dispatch-count caps. The wall-time watchdog terminates only the adapter-owned worker process group. The total-token budget uses observed provider usage: a completed request may cross that threshold, its full response is preserved, and the worker stops before consuming that response or issuing another request. It is not a provider-side hard spend cap. Missing usage stops the run because total accounting cannot be verified. OpenAI SDK automatic HTTP retries are disabled; native Agent validation retries are visible, separate attempts charged to the same counters.

```bash
HOST=/tmp/gymts-timecopilot-host/bin/python
$HOST -m gymts_timecopilot.cli --store /tmp/timecopilot-evidence --output /tmp/source.json \
  prepare --implementation /tmp/implementation.json --history 120 --horizon 12
```

The loader uses the real `statsforecast.utils.AirPassengers` 144 monthly observations, preserving its version and value digest. Only the first 120 observations enter the public numeric snapshot. The following 12 observations form the evaluation-only future. The source descriptor contains a private outcome ref for the evaluation driver; that descriptor and private ref are never passed to the Candidate. Dataset bytes and local stores are runtime artifacts, not package contents.

## Run and independently rescore

Run from outside the source tree:

```bash
cd /tmp
$HOST -I -m gymts_timecopilot.cli --store /tmp/timecopilot-evidence --output /tmp/evaluation.json \
  evaluate --source /tmp/source.json --params /tmp/params.json
$HOST -I -m gymts_timecopilot.cli --store /tmp/timecopilot-evidence --output /tmp/rescore.json \
  rescore --previous /tmp/evaluation.json
```

`evaluate` invokes public `AutoBenchTS.evaluate`, seals the actual Run, attaches evaluation-only outcomes, and calls public `AutoBenchTS.score`. The report retains the initial outcome-insufficient evaluation and the independently scored evaluation. It exits nonzero if the native Run failed, while retaining its Run ID and failure evidence. Scoring uses exact dataset-revision/sample-token alignment.

Before attaching late outcomes, the CLI saves the initial report alongside its output as `evaluation.execution.json`. If the evaluation driver later fails, use `score --initial /tmp/evaluation.execution.json --source /tmp/source.json --params /tmp/params.json` with the same global options to score the existing sealed execution without rerunning the Agent. Repeated experiments reuse immutable outcome availability; different content under an existing reference revision fails explicitly.

`rescore` runs in a new process and explicitly forbids both Candidate construction and native backend dispatch. It verifies sealed result hashes before and after scoring. Stop the local LLM service before running it for an additional operational check. Neither operation changes the frozen core or the prior Run result.

For application code, open `GymTS(store, integrations=("timeseries", "timecopilot"))`; use `gymts_timecopilot.data.prepare_airpassengers`, `gymts_timecopilot.experiments.evaluation_spec`/`evaluate`, or supply your own neutral numeric snapshot and public evaluation spec. Other Candidates can consume the same neutral task without TimeCopilot. Other sources or scorers can be substituted through the public contracts independently.

## Verify, update and remove

```bash
/tmp/gymts-timecopilot-host/bin/python -I -m unittest discover \
  -s /path/to/complete-checkout/adapters/timecopilot/tests -v
```

Contract tests use explicitly labelled event fixtures and require no model or scientific imports. They do not count as a real native Agent validation. Native acceptance requires a real local model response, all four original tool stages, at least two CV models, final-model/result consistency, successful independent future scoring, persisted failure/budget evidence when triggered, and a fresh-process rescore with the backend forbidden. Build and inspect wheel/sdist, install wheels into fresh environments outside the checkout, and verify frozen-core file hashes against the selected core wheel. Preserve the real Run IDs, model identity, dependency freeze and reports as evidence.

The current CPU contract and lifecycle suite has passed 13 tests. Its five process-lifecycle regressions use actual owned `sleep` processes: host SIGKILL/SIGTERM, a parent that exits before the worker arms its guard, rejection of a shared session, and cleanup after the worker leader has exited. Unrelated process groups stay alive. These checks do not constitute a successful native Agent run.

To replace or remove this integration, stop enabling `timecopilot`, then uninstall `gymts-timecopilot`. Existing sealed records and CAS artifacts remain available. In frozen core 0.5, AutoBenchTS still resolves the Candidate manifest to compare implementation identities during rescore: keep this lightweight wrapper installed/enabled together with the scorer/domain package when rescoring. The heavy native TimeCopilot environment and LLM service can be absent or forbidden; neither is loaded by registration or scoring. Complete removal of Candidate metadata during rescore is a recorded core limitation, not a capability claimed by this adapter. Upgrade this adapter independently. A new upstream revision requires a new supported adapter release and compatibility/native acceptance checks; never silently resolve `main` or `latest` at runtime. If a native requirement cannot fit public contracts, document the concrete failing case and why an adapter cannot handle it, then discuss the minimum core change and old-project compatibility before editing core. Keep a fixed core version for acceptance.

## Real native acceptance (2026-10-21)

The native Agent successfully completed a real local-14B experiment on public AirPassengers history with independent future targets. The model selected AutoETS itself, compared multiple models including SeasonalNaive, and consumed unchanged returns from all four native tools. The complete checkpoint content-tree SHA-256 is `d0d6f379d2324a9748b6c5e45179102113f9887fb22e0872b0c9480556c6c935`. This recipe used explicitly user-approved `tool_choice_mode=auto`; native tools and output validators remained in place. The core stayed on the same F0 wheel with all 39 installed file hashes verified.

| Evidence | Actual result |
| --- | --- |
| Run | `run_654e248d308a48c9a1e7ca45ca802c78` |
| Independent Evaluation | `evaluation_e06bc7e353c14b86ac8417b13229cee6` |
| Model/tool calls | 6 successful HTTP ModelCalls, 4 successful native ToolCalls: feature, cross-validation, forecast and anomaly stages |
| Provider usage | 31,389 total tokens across the six requests; no missing usage |
| Agent-selected model | AutoETS |
| Future MAE / RMSE | `44.41334215619239` / `52.018265022593305` |
| Metric counts | Both eligible=1, scored=1: one forecast unit with 12 withheld future points |
| Evaluation verdict | `insufficient_evidence` because `gates=[]`; engineering completion is not a quality-threshold pass |
| Service-stopped fresh rescore | `evaluation_a30df0bae04d4424a8fa1c4ae6bc4ad9`; identical metrics and unchanged sealed result/event hashes |

The fresh rescore forbade Popen, Candidate construction and native dispatch, and imported no torch, TimeCopilot, PydanticAI or statsforecast. Its prior guarded rescore was `evaluation_6b91f9b88e9c46b192d451e5e357f455`. All three earlier real failures remain recorded: unavailable feature selection by 7B; repeated features after enum publication exhausting 12 tool calls; and repeated stages by 14B under `required` exhausting the same cap. Success did not reset their budgets. Repeated late-outcome availability and missing-Run denominator regressions are covered without rerunning those Agents.

See the [small machine-readable acceptance summary](examples/native-validation-2026-10-21.json). Complete model files, transcripts, future values and active CAS stay in the local acceptance workspace. This single-series experiment establishes an Agent/tool/evaluation loop, not forecasting superiority or paper reproduction. The IO profile does not claim native token IDs or logprobs for RL training.

## License

This GymTS wrapper is distributed under [MIT](LICENSE). TimeCopilot and every dependency, dataset and model retain their own licenses; this license does not relicense third-party code, data or weights.
