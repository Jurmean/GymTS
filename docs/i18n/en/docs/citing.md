# Citation and experiment reproduction

If GymTS supports your research or engineering results, cite the actual software version or commit, and separately cite the models, datasets, algorithms, and upstream projects used. The repository provides [CITATION.cff](../CITATION.cff); no verifiable GymTS paper, DOI, or archive publication date is currently specified.

GymTS uses the [MIT License](../LICENSE), identified as `MIT` in `CITATION.cff`. Citation does not replace preservation of copyright and license notices; third-party models, datasets, and upstream projects retain their own terms.

## Software citation

The following template describes the current working tree. For a released version, replace the version, commit, and access date with real values. Do not attribute `Unreleased` working-tree results to an unverified public release.

```bibtex
@software{gymts,
  author = {{GymTS contributors}},
  title = {GymTS: Time-series experiment execution and independent evaluation},
  version = {0.5.0},
  url = {https://github.com/Jurmean/GymTS},
  note = {Record the exact commit or source archive hash used in your experiment}
}
```

## What reproduction materials should contain

- Actual GymTS, adapter, and native dependency versions/commits, plus model and dataset artifact hashes.
- Fixed ExperimentSpec / EvaluationSpec, resolved plan, seeds, execution limits, and visibility scope.
- Runtime status, all expected units, missing/invalid/failed counts, fixed scoring policies, and independent reference versions.
- Sealed Run / CAS / Snapshot and evaluation report references, or authorized access to those materials.
- Separate use/distribution permissions for data, models, and code; private answers and access tokens must not become public attachments.

Passing an engineering Gate does not establish better model quality. Reproduction notes must distinguish interface validation, training parameter updates, metric results, and production service acceptance. Keep original Runs unchanged and create new reports for new scoring. See the [user guide](user-guide.md).
