# gymts-chatts

An independently distributed adapter for ChatTS-Bench sources and native ChatTS/text models, not the ChatTS product interface. The `gymts` core does not contain this package. It depends on `gymts>=0.5,<0.6` and shared domain package `gymts-timeseries>=0.2,<0.3`, not TimeSigma, LibraryTS, or RL adapters.

Install the core and adapter from the main repository root:

```bash
python3 -m pip install . ./adapters/timeseries ./adapters/chatts
gymts-chatts --help
```

After separately installing built `gymts` and `gymts-chatts` wheels, the same commands work from any directory without `PYTHONPATH`. Installation neither activates plugins nor runs source generators. Components register only through explicit `GymTS(integrations=("chatts",))`, `gym.enable_integration("chatts")`, or `gymts --integration chatts ...`. The dedicated `gymts-chatts` pipeline activates the integration itself.

```python
from gymts import GymTS

with GymTS("/tmp/chatts-experiment", integrations=("chatts",)) as gym:
    print(gym.enabled_integrations)
```

The Python import location is `gymts_chatts`; the old `gymts.integrations.chatts` path has been removed. Component IDs, versions, task protocols, data schemas, and historical records retain their identities, such as `chatts-synthetic-qa@1.0.0` and `gymts.task/chatts-qa/1`. Install and enable the adapter to score original Runs without converting historical artifacts.

New experiments default to shared `gymts.task/timeseries-qa/1`: sources provide only series/context/public annotations; Tasks generate question and response_schema; model codecs then generate messages, ChatTS placeholders, and native array requests. Generic numeric Sources and seven Tasks/Scorers belong to an independent shared domain package. New Candidates here are `timeseries-chatts-http`, `timeseries-text-http`, and `timeseries-signal-baseline`. Tasks work with other sources/LibraryTS models through the same numeric contract without importing this package.

This is a **derived canonical-prompt experiment**. Shared Tasks generate question text instead of original profile messages, so it is not equivalent to the original benchmark prompt. Original instructions remain complete in private raw-source artifacts and do not enter new TaskInputs. Neutral import Manifests, pipeline summaries, and per-task summaries record `prompt_policy`, with `original_source_messages_used=false` and `equivalent_to_original_benchmark_prompt=false`; the formal EvaluationReport public schema is unchanged. Use the legacy path to evaluate original question instructions.

`run_pipeline` / `gymts-chatts` use this path by default. The historical path uses `run_legacy_pipeline` / `gymts-chatts --legacy` and the example `.legacy.json` connection configuration. All old `/1` schemas, component IDs, and source semantic checks retain their values. Original benchmark task identities remain public source constraints; changing Task cannot reuse original gold references. Generic JSON/CSV sources with `annotations={}` allow different compatible Tasks on the same data.

Data generation requires a compatible ChatTS generator repository or existing profiles separately. Generators, data, weights, and inference services are not in the wheel. HTTP Candidates use only the standard library, download no weights by default, and call no paid services. See the [complete integration guide](../../docs/chatts-integration.md) and package [connection examples](examples/README.md).

This package includes independent regression tests and fixtures. After installing the core and this package, run:

```bash
python3 -m unittest discover -s adapters/chatts/tests -p 'test_*.py'
```

After extracting the package sdist, run `python3 -m unittest discover -s tests -p 'test_*.py'` from its root; main-repository examples and other adapters are unnecessary.

New Source/Task versions provide pure `describe_spec` and configuration compatibility checks; `gym.plan`/`gym.validate` neither reads snapshots nor connects to model services. Baseline task_id mismatches in legacy and neutral paths fail during planning. Sample-specific series/horizon/benchmark constraints are checked inside Runs with retained failure evidence. CandidateContext supplies execution seeds without changing CandidateSpec identity: text OpenAI routes and ChatTS vLLM-envelope routes send request parameter `seed`; the old `chatts-timeseries/v1` route records intent without adding an unknown parameter. Deployments, request artifacts, and output evidence record `requested_seed`, `parameter_sent`, and `backend_enforcement=unverified`; server sampling determinism remains unverified.

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
