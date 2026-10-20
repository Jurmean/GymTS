# gymts-gymnasium

Independent Gymnasium simulation Environment adapter for GymTS 0.5. It depends
on the external neutral `gymts-interaction` domain, not another project adapter.
GymTS core has no Gymnasium import or dependency.

Install the three wheels (core, interaction, gymnasium) and `gymnasium==1.2.1`,
using Python 3.10 or newer for the native Gymnasium runtime,
then enable `GymTS('/tmp/gymts-simulation', integrations=('interaction','gymnasium'))`.
`gymts_gymnasium.environment_spec` constructs a fixed versioned native make
configuration. `gymts_interaction.experiments.evaluation_spec` builds an ordinary
AutoBenchTS EvaluationSpec. Run `examples/native_cpu.py --output /tmp/gymts-gymnasium-demo`.

Each Run owns one freshly created native environment, calls reset(seed) once,
executes one native step per authorized act, consumes the cached transition on
observe, and closes only its own instance. Last transition and reward are kept
even when terminal or exactly at the decision boundary. There is no automatic
reset, repeated act, hidden render loop or Gymnasium training implementation.
Independent scoring and rescoring read sealed events and never step the backend.

The public observation is converted losslessly from supported Gymnasium JSON/
NumPy values. Supported spaces are Discrete, Box, MultiDiscrete, MultiBinary,
Tuple and Dict; unsupported custom spaces fail explicitly. Actions are JSON
objects `{"action": <native action>}` and are checked against the actual space.
Info is hidden by default; only explicitly configured public_info_keys are
exposed. Do not allowlist a simulator's hidden truth. NaN/infinite observations
fail rather than silently change; infinite Box metadata bounds are strings.
Attach, vector environments, auto-reset wrappers, external mutable registrations
and arbitrary custom backend source attestation are outside this adapter's
verified scope. Version plus registered entry point/config are recorded; an
installed package version is not a cryptographic attestation of all dependencies.

Verified against the official Gymnasium reset/step API:
https://gymnasium.farama.org/api/env/

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
