# EnvironmentTS environment integration

Current core is **0.6.0**, with interface specification **1.4.0**. GymTS focuses on **storing data, connecting data sources, organizing experiments, and recording experiments**. EnvironmentTS owns source definitions, dataset snapshots, collection windows, lineage, execution, and evidence; AutoBenchTS owns benchmarks, independent evaluation, and rescoring. Formats, generators, native SDKs, and domain scoring remain in adapters.

Current F2.1 technical acceptance passed. See the [experiment organization guide](experiment-organization.md) for fixed data references, stages, attempt records, queries, and explicit build publication, and the [current acceptance report](reports/experiment-organization-2026-10-21.json) for identities, scope, and limitations. `run_data` still composes source binding, the original experiment, and capture without replacing real Task/Candidates. Four-kind data rationale and an executable data workflow remain in [ADR 0001](adr/0001-core-data-source-catalog.md) and the [user guide](user-guide.md#65-四类来源实际快照与回流).

The historical Environment-integration verification dated 2026-10-19 (Shanghai) covers synthetic data, static datasets, advancing simulations, and external live systems. HF column parsing, Gymnasium/OpenEnv calls, and PromQL remain outside core. Its actual Runs, native versions, distribution checks, and archive hashes remain in the [historical acceptance index](reports/environment-acceptance-2026-10-19.json). The 2026-10-19 and F1 evidence below retains its original identity; it is not relabeled as new F2.1 native execution.

## Historical F1: Frozen 0.5.1 Four-Kind Core Data Acceptance

Core F1 was frozen before the [independent four-source example](../examples/data_organization/README.md) was installed outside source. Core APIs own source definitions, assets, snapshots, capture and lineage; the package only composes existing providers, domain projections and experiment configuration. It changes no core files and adds no separate catalog, executor or evaluator.

| Kind | Real source and fixed view | Actual execution and evidence |
| --- | --- | --- |
| static | AirPassengers loaded by fixed native LibraryTS: 144 points, 132 public history plus 12 independent future values; one numeric input row | Native NaiveForecaster drift fit and independent held-out MAE/RMSE |
| synthetic | Original ChatTS numerical generator, seed 27: 40 points, 32 public history plus eight independent future values; one numeric input row | Reuses independent forecast Task/Candidate/Scorer without rewriting the generator |
| simulation | Real Gymnasium FrozenLake, reset seed 19 | Six real actions, seven observations, native terminal state and return=1 retained |
| live_testbed | Genuine Prometheus scraping a local exporter | 137 observation batches and 11 results; actual time/capture scope retained, with scoring after the service stops |

The result is four real Runs, four independent AutoBenchTS evaluations and four lightweight-environment rescores. Technical Gates check execution and coverage only, not forecast quality, autonomous Agent tool capability or causal online prediction. The rescore environment has no NumPy/SciPy/pandas/sktime/Gymnasium/torch/Transformers, and forbids Run execution and Environment/Candidate construction. All metrics, coverage and sealed-Run hashes remain unchanged.

Separately, `data_home` was copied to another directory, external services stopped and the original Run store moved aside. A new Run root reread all four datasets, capture metadata and every portable attachment. Independent scoring still worked after restoring the original Run store. Offline dataset readability and historical Run rescoring are separate evidence; a dataset copy is not a complete execution archive.

The fixed F1 wheel SHA-256 before/after real execution is `8944f39ffe516dbe22b7800f57fd18266cf6b3a4e84cf3a35b32cb6261ac2f1a`; the core code-tree digest is `dad5d6a1785c4fa440a51dd4c93307f47ca000aa0d955daa70e68e32dcfac319`. All 168 core regressions plus wheel/sdist and installation-outside-source checks completed separately. Rebuilt distribution-wheel bytes may differ from the actual F1 wheel, while matching the same code tree. See the [machine-readable report](reports/core-data-organization-2026-10-21.json) for identities, Run/evaluation/rescore IDs and scope. The existing sixteen-package F1 compatibility check discovered 407 tests: 346 executed passes and 61 optional-dependency skips. It includes that round’s AReaL V13 CPU draft without relabeling native training or held-out evaluation. Joint activation of sixteen packages, and fifteen after removing AReaL, also passed core execution and sealed-output rescoring. Complete four-source evidence was archived and restored into a fresh directory: 567 CAS references and 60 data-object digests were checked, followed by successful four-source reads and lightweight rescoring again. No Git/PyPI publication occurred, and F0 or pending AReaL status did not change.

## Four source kinds and where the stacks fit

| Source | Integration and public data | Actual verification this round | Scope |
| --- | --- | --- | --- |
| Synthetic data | Existing generators or external ChatTS generators produce fixed public observations | Deterministic forecasting, counter, evaluation, and late-reference rescoring rerun against the frozen core | ChatTS generation was not rerun; existing independent integration and original contracts remain |
| Static datasets | Independent `gymts-hf-datasets` explicitly freezes HF Hub, save_to_disk, or local_files as long-term resources | Fixed official Monash commit, three loading paths, offline execution, and original-Run rescoring | Limited one-dimensional numeric forecasting views; not full HF Hub, arbitrary modalities, or the full Monash benchmark |
| Advancing simulations | Independent `gymts-gymnasium` creates an owned native environment; act advances one step and observe consumes its cache | Real FrozenLake and CartPole, native termination and scope boundaries, independent evaluation/rescoring | One episode; no vector environments, automatic reset, or bundled RL training backend |
| External services and live testbeds | `gymts-openenv` connects external stateful sessions; `gymts-prometheus` reads live metrics | Official OpenEnv Echo/Connect4 services and an actual Prometheus scraping service | Real local services verified; user production endpoints, authentication, and production control permissions unverified |

HF Datasets loads static resources; Gymnasium is a locally advancing simulation interface; OpenEnv defines external environment services; Prometheus provides live observability data. They are not new GymTS main modules, nor mandatory implementations for future projects. Other formats, simulators, or testbeds can register under the same public contracts.

`gymts-interaction` is a separately distributed neutral domain package shared by Gymnasium and OpenEnv for JSON state, control Tasks, example Candidates, and episode Scorers. Sharing does not make it core. HF supplies its forecasting domain contract. Prometheus owns no model, Task, or Scorer: its example reuses existing forecasting components through configuration. Toolsets, sources, Tasks, Candidates, and Scorers remain independently replaceable.

## Invocation and storage

Install the adapters you need, then prepare native dependencies and upstream services according to their READMEs. Run the following from the main repository; no paid models are involved:

```bash
python -m pip install .
python -m pip install './adapters/hf_datasets[runtime]'
python -m pip install ./adapters/interaction './adapters/gymnasium[runtime]'
python -m pip install ./adapters/openenv ./adapters/prometheus
```

Gymnasium 1.2.1 and the official OpenEnv native runtime used here require Python 3.10+. Installing the OpenEnv adapter does not download or start a server. Prepare its SDK and environment services separately from fixed upstream sources.

| Scenario | Runnable entry point |
| --- | --- |
| Deterministic synthesis and late evaluation | `python examples/quickstart.py --root /tmp/gymts-synthetic-new` |
| HF static source | `python adapters/hf_datasets/examples/hf_static.py --work /tmp/gymts-hf-new --report /tmp/gymts-hf-new/report.json` |
| Gymnasium simulation | `python adapters/gymnasium/examples/native_cpu.py --output /tmp/gymts-gymnasium-new` |
| Official OpenEnv Echo service | `python adapters/openenv/examples/echo_roundtrip.py --owned-local-echo --root /tmp/gymts-openenv-new` |
| Official OpenEnv Connect4 service | `python adapters/openenv/examples/echo_roundtrip.py --owned-local-server --environment connect4 --root /tmp/gymts-connect4-new` |
| Prometheus live source | `python adapters/prometheus/examples/native_server_demo.py --output /tmp/gymts-prometheus-new --prometheus-binary /path/to/prometheus` |

Use nonexistent local output directories for examples. The initial HF freeze may require network access. Once frozen, execution uses manifests and content artifacts without the original HF directory or an online service. OpenEnv examples launch official upstream services; Prometheus examples launch a real binary and exporter. The harness that owns each process stops it; the Environment itself must not stop someone else's service.

Python still calls the native services, without another executor or report system:

```python
from gymts import GymTS
from gymts_gymnasium import environment_spec
from gymts_interaction.experiments import evaluation_spec, rescore_spec

candidate = {
    "adapter": "interaction-sequence", "version": "1.0.0",
    "artifact": None, "inherited_state": [],
    "params": {"actions": [{"action": a} for a in (2, 2, 1, 1, 1, 2)],
               "repeat_last": False},
}
spec = evaluation_spec(
    environment_spec("FrozenLake-v1", kwargs={"is_slippery": False}),
    candidate, scope_end=6, seeds=(19, 29),
)
with GymTS("/tmp/gymts-python-new", integrations=("interaction", "gymnasium")) as gym:
    report = gym.autobench.evaluate(spec)
    rescored = gym.autobench.score(rescore_spec(gym, report, spec))
```

Long-term static resources live in `data_home`, including immutable source bytes, public projections, private references, cards, and version manifests; `cache_home` is rebuildable. Active SQLite/CAS lives in a local POSIX Run root and is archived to shared/object storage only after sealing. Live and simulation sources preserve actual observations, provenance, operations, and responses. A deployment name is not an immutable version of future data. Explicitly freeze captured observations when identical-input replay is needed.

## Visibility, clocks, and ownership

Static public contexts and held-out references are stored separately. HF evaluation views exported by this version are evaluation-only: training, prepare, and dataset_build are rejected. General HF training support does not authorize training on this view. The five existing benchmark attachments also remain evaluation-only.

Simulations use step clocks. start resets once; act performs one native step; observe consumes one cached transition. Duplicate requests, another action before consuming a transition, or actions after termination must not execute a second step. Final states and rewards are retained, including action results exactly at the decision boundary. Scope ending is expressed through read_scope_end and the domain metric scope_limited, without inventing native truncated. Gymnasium checks native reset seed; OpenEnv integration rejects non-null seeds when it cannot enforce them.

OpenEnv retains sessions through the official SDK's persistent WebSocket, rather than treating stateless HTTP reset/step as one episode. The Run owns a newly created WS session, while the host is externally owned; finish releases only this Run's resources. Native OpenEnv has only done. Unknown causes remain in external domain state; EndInfo uses existing source_exhausted with detail.reason=native_done_unclassified, without a new core enum. Indeterminate terminated/truncated metrics report missing. Unknown rewards remain null and make return metrics insufficient, rather than turning into 0.

Prometheus supports only attach, seed=null, and read-only numeric metrics; it cannot reset or control the actual system. Wall clock uses actual time. Sample time, HTTP receipt availability, and delivery coverage are recorded separately. Task history queries read delivered immutable snapshots only, never arbitrary out-of-scope PromQL. The reference forecasting Task in the current example records decision time as sample time, before HTTP receipt; this round therefore does not validate causal online forecasting. Multiple Candidates cannot sequentially rerun the same real-world interval either: assign separate windows or use a common frozen replay.

EnvironmentSummary retains formal §6.7 fields and closed/detached/not_started values. Unconsumed transitions are preserved via artifact_refs; unknown operations enter pending_operations. Errors retain operation_id and possible side effects, without automatic resend. Recording failures still trigger best-effort cleanup of owned resources; failure to publish evidence must not leak environments. Restricted services are trusted-plugin API boundaries, not process sandboxes.

## Independent evaluation and frozen-core verification

AutoBenchTS evaluate fixes expected units before running Candidates; score rescores fixed old Runs. Static forecasting Scorers use private held-out references. Interaction Scorers independently derive episode metrics from sealed states, operations, and receipts. The Prometheus example uses an explicit external fixture reference. Rescoring must not recreate simulators, call models, or request live services. Technical Gates check execution and coverage, not model quality.

This round fixed core **0.5.0**, code tree
`8990de5a08378498c47853f238f7ae27c6f0072c1ea61bd29328294c6b8b9e20`,
and acceptance wheel SHA-256
`cea1ab0bdccf479820d9e9cf20cfc4a82c733978e7c722151601067e8925d226`.
New sources were installed outside source directories and used public interfaces for execution, sealing, independent evaluation, and original-Run rescoring. Existing reports and archive indexes:

- [Synthetic source](reports/synthetic-environment-2026-10-19.json): existing generator/counter, late references, and unchanged original outputs.
- [HF static sources](reports/hf-environment-2026-10-19.json): fixed official data, three source modes, public/private separation, offline execution, and failure evidence.
- [Gymnasium simulation](reports/gymnasium-environment-2026-10-19.md): real FrozenLake/CartPole, final rewards, correct end semantics, independent evaluation, and rescoring.
- [OpenEnv external environments](reports/openenv-environment-2026-10-19.md): official Echo/Connect4, raw WS evidence, unknown causes, and no resend after faults.
- [Prometheus live source](reports/prometheus-environment-2026-10-19.json): actual scraping, independent references, network-free rescoring, invalid-query failure evidence, and a still-running host.

[Eleven-package distribution acceptance](reports/environment-adapter-package-check-2026-10-19.json) completed wheel/sdist builds, source rebuilds, installation outside source directories, coexistence, and removal. Minimal environments ran 319 tests: 265 passed and 54 skipped for missing optional native runtimes. Native environments separately passed interaction 14, Gymnasium 16, HF 8, OpenEnv 8, and Prometheus 12, with no skips. OpenEnv also rescored the same Runs without its SDK and after the original server stopped, showing scoring does not depend on native execution.

## Why this round required zero core changes

| Actual requirement or difference | Why an adapter can express it | Core decision and compatibility |
| --- | --- | --- |
| HF formats and fixed sources | Readers, Source, resource manifests, private Outcomes, and resolvers already have extension interfaces | No core changes; original benchmark and reading APIs remain |
| Simulation states and actual actions | Environment start/observe/act/finish and TaskRequest.command already exist | No core changes; a separate control domain package leaves old Tasks unaffected |
| Null reward, done-only signals, remote WS lifecycle | Native Payload uses an external domain schema; EndInfo.detail already permits additional source facts | No core changes; optional domain information does not coerce unknown causes into core flags |
| Live samples, receipt time, history snapshots | External advancement, wall clocks, waiting, coverage, permissions, and CAS already exist | No core changes; PromQL, caches, and source-time semantics stay in the adapter |
| Independent evaluation of final rewards and rescoring | ResultsView.event_snapshot_ref already exposes fixed sealed events | No core changes; native AutoBenchTS execution/reporting remains the sole evaluation system |

When a real requirement cannot fit these interfaces, record the concrete failure, why adapters cannot solve it, the proposed interface, and existing-project regressions before changing core. Different native fields in one stack do not justify project-name branches. General remote workers, isolation, forced interruption, recovery, and arbitrary control testbeds still need separate acceptance.

Example Candidates in this round use fixed actions or simple numeric baselines, verifying environment interfaces and evidence closure. A general loop where an Agent selects external tools, consumes results, and continues reasoning has not been accepted. Native environment calls also do not prove autonomous tool selection. See [Agents and external toolsets](agent-toolsets.md) for placement and responsibilities.
