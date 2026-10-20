# An external GymTS Candidate in one small package

This teaching package implements `example-drift@1.0.0` for the existing
`gymts.task/forecast/1` contract. It reuses GymTS's reference replay Environment,
`window_forecast` Task and `forecast-mae` Scorer. It contains no data importer,
new evaluator, model service or core modification.

The prediction extrapolates the last two valid samples to `target_time`, with
`damping` in `[0, 1]`. One valid sample gives a last-value prediction; no valid
samples gives an explicit missing prediction. This deterministic algorithm is
an integration tutorial, not an autonomous Agent or a forecasting benchmark.

## Install from a full repository checkout

Use Python 3.9 or newer. The tutorial lives in the Git repository; it is excluded
from the core wheel and source distribution. From the repository root:

```sh
python -m venv /tmp/gymts-adapter-tutorial-env
/tmp/gymts-adapter-tutorial-env/bin/python -m pip install . ./examples/adapters/minimal_demo
cd /tmp
/tmp/gymts-adapter-tutorial-env/bin/python -I -m gymts_minimal_demo --root /tmp/gymts-adapter-tutorial-runs
```

Choose a fresh records directory when repeating the demonstration. The installed
distribution is `gymts-minimal-demo==0.1.0`; its integration name is
`minimal-demo`, and its versioned Candidate name is `example-drift@1.0.0`.
These are separate identities.

The command performs real native `AutoBenchTS.evaluate` and `score` calls. It
first records missing labels as `insufficient_evidence`, attaches a separately
derived linear-ramp reference, and scores drift and last-value outputs. Expected
aggregate MAE is `drift=0.0`, `last-value=1.0`. It then forbids Candidate inference
and repeats scoring, checking that Run IDs, sealed results and event hashes do
not change. No external data, network, credentials or accelerator is required.

The records directory also contains `receipt.json`, `score-spec.json` and the
public `candidate-declaration.json` for inspection and later rescoring.

## Discover, then explicitly enable

```python
from gymts import GymTS

print(GymTS.available_integrations())  # Reads entry-point metadata only.

with GymTS(root="/tmp/my-runs", integrations=("minimal-demo",)) as gym:
    candidate = {
        "adapter": "example-drift", "version": "1.0.0",
        "artifact": None, "params": {"damping": 1.0}, "inherited_state": [],
    }
    # Use candidate in an ExperimentSpec or an EvaluationSpec.
```

Installation alone does not activate the plugin. The `register` entry point only
registers a parameter schema and a Candidate factory. It does not open a model
or read data. The smoke command additionally patches the Candidate constructor
to fail during `validate/plan`, proving that assembly does not create a method
session.

## Uninstall and independently rescore

Keep the absolute checkout path before changing directories:

```sh
GYMTS_CHECKOUT=/absolute/path/to/Jurmean-GymTS
/tmp/gymts-adapter-tutorial-env/bin/python -m pip uninstall -y gymts-minimal-demo
cd /tmp
/tmp/gymts-adapter-tutorial-env/bin/python -I "$GYMTS_CHECKOUT/examples/adapters/minimal_demo/rescore_without_adapter.py" \
  --root /tmp/gymts-adapter-tutorial-runs --require-absent
```

Expected: `verdict=pass`, `same_run_ids=true`,
`run_evidence_unchanged=true`, `optional_adapter_required=false`.
The script restores the archived Candidate manifest and parameter schema, with
a factory that always raises if execution is attempted. AutoBenchTS requires
this public declaration for compatibility checks even when no inference occurs.
No original algorithm is installed or loaded. The task/result contract and
Scorer remain available in the core reference examples. In general, rescoring
requires the relevant declarations, original result schemas, compatible Scorer
and immutable evidence. Removing a package that supplies these contracts
requires preserving or independently installing them; arbitrary plugin removal
is not a promise of universal decoding.

For lifecycle, domain contracts, other provider types and release requirements,
see [the adapter development guide](../../../docs/adapter-development.md).

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
