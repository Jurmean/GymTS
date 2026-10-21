# An independent staged experiment over registered data

This small package imports an existing official ETTh1 wide CSV view into the
GymTS data catalog. Three explicitly registered external stage executors handle
the CSV conversion, public replay projection and independent reference
projection. GymTS owns immutable definitions, resolved inputs, dependencies,
attempts, Run linkage, stage status, evidence and query. No core files are changed.

The four stages are `import -> execute -> references -> score`. Execution uses
the existing core replay Environment, `window_forecast` Task, `last-value` and
`window-mean` Candidates. The independent core `forecast-mae` Scorer evaluates
the original sealed Runs. Initial execution has no references and retains
`insufficient_evidence`; references arrive in a separate stage. No acceptance
Gate is declared, so a completed numerical score also retains that verdict.

## Run from installed packages

Use Python 3.9 or newer and a local official `ETTh1.csv`. No data, model, network
or scientific dependency is installed by this package. From the checkout root:

```sh
python -m venv /tmp/gymts-organization-example-env
/tmp/gymts-organization-example-env/bin/python -m pip install . ./examples/adapters/organization_demo
cd /tmp
/tmp/gymts-organization-example-env/bin/python -I -B -m gymts_organization_demo \
  --work /tmp/gymts-organization-example \
  --csv /absolute/path/to/ETTh1.csv \
  --source-revision 1d16c8f4f943005d613b5bc962e9eeb06058cf07
```

The expected upstream source is
[ETDataset / ETT-small / ETTh1.csv](https://github.com/zhouhaoyi/ETDataset/blob/1d16c8f4f943005d613b5bc962e9eeb06058cf07/ETT-small/ETTh1.csv).
The receipt records the full supplied file SHA, selection and immutable CSV
artifact. The revision is caller-provided provenance; the example does not
authenticate a GitHub download. It selects the first 32 hourly OT values by
default. Naive upstream timestamps are replayed on a UTC coordinate, explicitly
without claiming the original dataset timezone was UTC.

This is rolling one-hour-ahead evaluation: each Candidate sees only its current
three-observation window; the future target is independently joined afterward.
The builtin demonstration Task accepts the generic unit `value`; the adapter
keeps raw OT magnitudes unchanged and records the original `degC` unit in dataset
features rather than changing the frozen Task contract.
For 32 observations there are 29 scored predictions per Candidate. The reference
stage also computes the two expected MAEs directly from the registered numbers,
independently of the Scorer and model outputs. This small view is an integration
check, not a full ETT benchmark or a model-quality claim. Training is forbidden
by the registered dataset/source policy.

## Read and rescore after uninstall

Keep the script path before leaving the checkout:

```sh
GYMTS_CHECKOUT=/absolute/path/to/Jurmean-GymTS
/tmp/gymts-organization-example-env/bin/python -m pip uninstall -y gymts-organization-demo
cd /tmp
/tmp/gymts-organization-example-env/bin/python -I -B \
  "$GYMTS_CHECKOUT/examples/adapters/organization_demo/rescore_without_adapter.py" \
  --work /tmp/gymts-organization-example --require-absent
```

The standalone script imports only GymTS and the standard library. It checks
public DatasetHandle reading, group/dataset queries, original Run evidence and
fresh-process rescoring while Candidate inference, Environment construction and
execution are forbidden. It explicitly reruns only the builtin `score` stage:
completed external stages are reused, and the new score attempt/report remain
linked to the same experiment group. Installing the external executor package is required
to invoke its stages again; it is unnecessary for inspecting the persisted
organization or independently scoring these core-contract results.

## License

GymTS-owned example code is licensed under the [MIT License](LICENSE).
The upstream dataset retains its own provenance and terms; no data is bundled
or relicensed by this example.
