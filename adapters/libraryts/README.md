# gymts-libraryts

Independently installable tools, dataset loaders, stateless estimator Candidates
and forecast Scorer for the user-selected
[NetmanAIOps/sktime](https://github.com/NetmanAIOps/sktime) LibraryTS repository.
The fixed implementation is commit
`080f4c3c3695f239e328548bac7d7a3ef7aa9127` (source version sktime 0.40.1).
It is the repository's real estimator and LabTS/TSBox Playground APIs; this
adapter does not substitute another PyPI sktime or reimplement those algorithms.

Install GymTS core, the shared domain package and this adapter independently:

```bash
python -m pip install /path/to/Jurmean-GymTS
python -m pip install /path/to/Jurmean-GymTS/adapters/timeseries
python -m pip install '/path/to/Jurmean-GymTS/adapters/libraryts[runtime]'
```

Native work executes in an explicit scientific interpreter. Install the same
three distributions there plus the fixed upstream source as an editable package:

```bash
/path/to/native-env/bin/python -m pip install --no-deps -e /path/to/fixed-sktime
```

Prepare that interpreter's scientific dependencies using this adapter's
`runtime` extra or the fixed upstream dependency declarations. `analysis` adds
statsmodels and numba for optional seasonality/distance tools. Core/discovery
require neither scientific packages nor an installed upstream checkout.

The worker starts from an unrelated temporary directory with `-I` and no
`PYTHONPATH` injection. It checks Git origin, exact commit, tracked cleanliness,
actual imported sktime paths and hashes of loaded native modules. The original
Playground scripts use top-level imports; the isolated worker explicitly loads
their fixed tracked files with importlib, refuses conflicting existing modules,
and records those paths/hashes. It does not modify upstream files or sys.path.

```python
from gymts import GymTS
from gymts_libraryts.tools import LibraryTSTools

implementation = {
    'repository': '/path/to/fixed-sktime',
    'revision': '080f4c3c3695f239e328548bac7d7a3ef7aa9127',
    'python': '/path/to/native-env/bin/python',
}
with GymTS('/tmp/gymts-state', integrations=('libraryts',)) as gym:
    tools = LibraryTSTools(gym.artifacts, implementation)
    call = tools.call('forecast.naive', {'values': [1, 2, 3], 'horizons': [1, 2]},
                      {'strategy': 'drift'})
    assert call['output']['predictions'] == [4, 5]
```

Standalone calls save requests before execution and success/failure responses
as CAS artifacts. They create no fictitious Run. The ten callable entries are:

| Entry | Fixed native API |
| --- | --- |
| forecast.naive | NaiveForecaster.fit/predict |
| forecast.polynomial | PolynomialTrendForecaster.fit/predict |
| detect.threshold | ThresholdDetector.fit_predict, segment semantics |
| analyze.seasonality | SeasonalityACF or SeasonalityPeriodogram |
| distance.euclidean | sktime.distances.distance |
| labts.catalog | playground.catalog.build_catalog |
| labts.run | playground.runners.run_experiment |
| labts.analyze | playground.analyzer.run_analysis |
| labts.metrics | playground.metrics.resolve_metrics/compute_metric |
| dataset.load | vendored airline, lynx or shampoo-sales loaders |

`labts.run` is explicitly a standalone native library experiment, whose bundled
metrics are library output. It does not create a GymTS Run or an AutoBenchTS
report. Candidate execution never delegates to this entry: it sends only the
current authorized TaskInput to the chosen estimator. Heavy methods and missing
soft dependencies fail explicitly; there is no simulated fallback.

`libraryts-qa/1.0.0` consumes the independent `gymts_timeseries` QA contract and
supports `forecast.numeric` and `pattern.trend_direction`, with one numeric
series per input. Choose `estimator='naive'` with `estimator_params={'strategy':
'drift'}` or `estimator='polynomial'` with `{'degree': 1}`. Both can replace each
other under the same source and Task; the adapter never imports ChatTS or RL.
The domain Task owns question construction, response schema, parsing and task
semantics. This package supplies model implementations, not another Task.

The Candidate is a **stateless current-window algorithm**: `prepare=load_only`
fixes its algorithm implementation and configuration; persistent policy updates
and training views are unsupported. Each infer constructs a fresh native
estimator, genuinely fits the current authorized input series, predicts, and
discards that temporary estimator. This input conditioning reads no future
values or labels and reuses no state across calls. Evidence records that native
fit **did occur**, its fitted-state digest and polynomial coefficients. The
fixed `model_revision` identifies the algorithm definition/configuration,
not a claim of pretrained learned weights or a persisted checkpoint.

Set `recording.model_calls='io'` to capture real model and child ToolCall events
under Runner-assigned input/output identities. No token IDs, logprobs or hidden
reasoning are fabricated. With capture disabled, native request/response CAS
references remain Candidate artifacts. Internal estimator tools are ordinary
computations on existing input, so operation_id/environment_request_id are
null; new environment reads or actions would require TaskRequest/Runner.

`gymts_libraryts.data.load_dataset` uses a real native loader and returns a
public neutral snapshot and a separate evaluation-only holdout artifact.
It does not choose a Task or construct model messages. The same snapshot can
be bound to forecast or trend Tasks, and the same Task can use numerical CSV
or another compatible source supplied by `gymts_timeseries`.

`libraryts-forecast-scorer/1.0.0` reuses the shared domain's alignment, parser,
eligibility and permission rules, and calls the original Playground MAE/RMSE
implementations on sealed predictions and independently supplied outcomes.
AutoBenchTS remains the only evaluation/score/report owner.

See `examples/libraryts_demo.py` for a complete dataset → two native Candidates
→ sealed Runs → separate outcomes → AutoBenchTS fixed-output rescore flow.

The upstream `playground/trainer.py` provides actual persistent fit/save/load
support. Its top-level train/predict APIs also select catalog datasets, write
mutable model IDs and perform their own evaluation. Those are not exposed as
GymTS training adapters. If an external persistent training adapter is needed, it should reuse its
estimator fit/serialization boundaries on authorized fixed inputs and publish
immutable CAS model bundles, keeping evaluation in AutoBenchTS.

```bash
python -B -m unittest discover -s tests -p 'test_libraryts*.py' -v
GYMTS_LIBRARYTS_NATIVE_TESTS=1 GYMTS_LIBRARYTS_REPO=/path/to/fixed-sktime \
GYMTS_LIBRARYTS_PYTHON=/path/to/native-env/bin/python \
python -B -m unittest discover -s tests -p 'test_libraryts*.py' -v
```

Tests and examples are included in this package's sdist. Default tests do not
train native models, make provider requests or require source checkouts.
Native tests opt in to small CPU computations and vendored datasets.

Offline `gym.plan`/`gym.validate` use the generic compatibility hook to reject a
known task_id outside forecast/trend, persistent training or inherited state,
and a configured revision that differs from the fixed native source. They do
not inspect a checkout or construct an estimator. Source series arity and
horizon remain runtime checks when their values exist only in source bytes.
The manifest explicitly distinguishes its fresh native current-input fit from
persistent `prepare=fit`; `supports_fit=False` concerns the latter lifecycle.

## Role as an external Agent tool provider

LibraryTS is one interchangeable external toolkit, alongside other libraries or
MCP/API providers. Its algorithms, dependencies and asset platform remain outside
GymTS. The Agent chooses tools and arguments, the Agent SDK/platform invokes the
adapter, and results return to the same Agent for continuation. GymTS provides
generic experiment access boundaries and call evidence; it does not choose a
LibraryTS algorithm on the Agent's behalf.

Inside a Candidate, construct `LibraryTSTools(context['resources'],
implementation, traces=context['traces'], scope='current_input')` after opening
the session. This scope exposes only forecast.naive, forecast.polynomial,
detect.threshold, analyze.seasonality and distance.euclidean. It rejects dataset
loading, independent experiments and private evaluation tools before native
execution, retaining failed-call evidence. The fixed estimator Candidate uses
this scope even when call capture is disabled. A bound Run trace cannot be used
with standalone scope. Without Run binding, the explicit standalone API retains
all ten native entries for separately authorized host-side uses. Scope/effect
metadata belongs to this external adapter, not a core project registry.

`catalog()` checks configured source identities and can touch the checkout; use
it after opening resources, never as a pure plan/discovery hook. The Agent SDK
adapter still needs to map tool schemas, handler invocation and native call IDs.
This package does not provide a complete general Agent loop. `libraryts-qa` is a
fixed algorithm baseline, and its existing tests are not evidence of model-driven
tool selection. A real model -> tool -> result -> model continuation and a second
provider remain separate integration acceptance work.

Any read of new experiment-environment observations or control must go through
TaskRequest/Runner/Environment. Run-external research may call GymTS public
run/evaluate/score services and link real child Runs. The provider must never use
dataset.load or labts.run as a disguised current-input computation. See the
[framework tool/Agent boundary](../../docs/agent-toolsets.md).

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
