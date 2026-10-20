# gymts-timesigma

An independently installable TimeSigma adapter for GymTS 0.5. It supplies the
`timesigma` integration entry point and the `gymts-timesigma` command. Core
GymTS neither bundles this package nor imports it during integration discovery.

The adapter preserves the `timesigma-snapshot`, `timesigma-tsad`,
`timesigma-native`, and `timesigma-official` component IDs at version `1.0.0` and
the existing `/1` payload contracts. It uses the public GymTS registries,
EnvironmentTS, AutoBenchTS, records, and artifacts services. Installing or
removing the adapter does not change the core distribution.

Install the core and adapter as separate distributions. In a source checkout:

```bash
python -m pip install /path/to/Jurmean-GymTS
python -m pip install '/path/to/Jurmean-GymTS/adapters/timesigma[runtime]'
```

The `runtime` extra supplies NumPy for local `.npy` dataset import. Discovery
and explicit registration require only the core dependency; scientific imports
remain in the configured scientific interpreter.

Install this same adapter and core into the scientific environment as well.
That environment must also contain the original TimeSigma dependencies and the
fixed upstream checkout installed as a package (an editable install preserves
its source-path provenance):

```bash
/path/to/native-env/bin/python -m pip install --no-deps -e /path/to/TimeSigma-GymTS
/path/to/native-env/bin/python -m pip install /path/to/Jurmean-GymTS
/path/to/native-env/bin/python -m pip install /path/to/Jurmean-GymTS/adapters/timesigma
```

The required upstream revision is
`5a953c1a84d0a442d1c41b17b4e8aba8c013be10`; EasyTSAD must identify
`e7be92374a4543d7c52d6e34ef7047f4d6776be0`. Prepare their dependencies using
the upstream lockfile before installing this adapter. Workers use installed
`gymts_timesigma.*` modules from a temporary working directory. They do not add
source directories to `sys.path` or `PYTHONPATH`. Runtime source checks still
reject a different, dirty, or unexpectedly imported upstream checkout.

```python
from gymts import GymTS
from gymts_timesigma.data import import_dataset
from gymts_timesigma.pipeline import run_experiment

with GymTS('/tmp/gymts-state', integrations=('timesigma',)) as gym:
    data = import_dataset(gym, '/path/to/datasets', dataset='TODS',
                          schema='naive', curve_id='0',
                          source_repo='/path/to/TimeSigma-GymTS')
    report = run_experiment(gym, data, {
        'source_repo': '/path/to/TimeSigma-GymTS',
        'python': '/path/to/native-env/bin/python',
        'method': 'IsolationForest',
    }, execution_seed=1)
```

A run is one detector pipeline × one schema planning unit. Native methods,
preprocessing, membership and evaluation semantics are unchanged. Research
parent trajectories remain adapter artifacts referencing real core Runs;
this package does not supply the native Pi Agent loop or Memory publication.
Historical sealed runs retain their identities and can be scored with the
same registered component IDs after installing the adapter. Model bundles
continue to verify their exact recorded implementation bytes; relocation is
not permission to bypass a source-identity mismatch.

The source distribution contains the adapter tests and their local fixtures:

```bash
python -B -m unittest discover -s tests -p 'test_timesigma*.py' -v
```

Run from the adapter source directory or unpacked source distribution after
installing both wheels. Native CPU tests are opt-in using
`GYMTS_TIMESIGMA_NATIVE_TESTS=1`, `GYMTS_TIMESIGMA_REPO`, and
`GYMTS_TIMESIGMA_PYTHON`. Default tests do not invoke providers or native model
training. For the full API and evidence limits, see the GymTS repository's
`docs/timesigma-integration.md`.

`gym.plan` and `gym.validate` use pure `describe_spec` declarations and
configuration-only compatibility checks; they do not read arrays or bundles,
construct live roles, inspect checkouts, or launch native interpreters. They
reject known incompatible training/source schemas, load bundles, online updates
and the fixed IsolationForest binding's seed constraint. Planning-unit IDs,
Schema member lists, fitted bundle identity and array lengths are checked only
after the Run begins, because those facts reside in private resource bytes.

New pipeline configurations put the fitting seed in execution, leaving
CandidateSpec unchanged across repetitions. If an older CandidateSpec explicitly
contains `params.seed`, that value retains priority and provenance records
`seed_source=legacy_candidate_parameter` plus `requested_execution_seed`.
Without the legacy parameter, fitting uses the execution seed, or the historical
fallback 1 if it is absent. `load_only` retains the bundle's fitting seed and
never retrains in response to a new execution seed. Training provenance and
prediction evidence record the effective seed and its source. The native
IsolationForest binding currently permits fitting seed 1 only; AR can use other
nonnegative seeds.

`examples/frozen_core_cpu.py` runs one actual small AR CPU experiment on explicitly
synthetic arrays, calls the official scorer and scores the same sealed Run
again. Its JSON report includes installed/source core file-tree hashes before
and after, effective fitting seed, native fit/score/replay evidence and a CAS
archive. It is an integration check, not model-quality evidence. Run it from
outside the checkout after installing the frozen wheels; `--core-source` is a
read-only path to the core package tree whose unchanged identity to verify.

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
