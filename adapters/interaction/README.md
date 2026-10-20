# gymts-interaction

An independent, project-neutral control domain for GymTS 0.5. Install it alongside
an external environment adapter and enable `interaction` before that adapter.
It imports no Gymnasium, OpenEnv, model project, or service client.

`interaction-control` interprets a Candidate JSON action and requests the bound
Environment `act` operation through Runner. `interaction-fixed` and
`interaction-sequence` are small deterministic conformance policies; a production
Agent implements the same public input/output contracts and decides its actions.
The environment backend is never exposed to the Candidate as a Python object.

`CachedInteractionEnvironment` is a reusable external adapter utility. Subclasses
implement `_reset(seed)`, `_step(action)` and `_close()`. Start resets once; act
steps once and caches the transition; observe consumes that cache. Terminal
observations retain the final reward. There is no automatic episode reset,
repeated action retry, or deletion of an externally owned service.
If cancellation or a deadline interrupts the gap after act and before observe,
the sealed cleanup summary links that unconsumed public transition through its
artifact_refs. It is not
misrepresented as a consumed observation or a complete episode.

The wire is `gymts.interaction/state/1`: episode_id, step, observation (JSON),
reward (null at reset or when a backend supplies no reward), terminated,
truncated, and public info. A backend that supplies only an unclassified done
signal adds backend_done and end_cause="unclassified"; the two classification
flags then mean no classified cause was supplied, not that the cause is known
to be false. EndInfo.reason is source_exhausted with
detail.reason="native_done_unclassified", and termination metrics
report missing evidence rather than zero. Gymnasium retains its native classified
flags without this optional extension. The generic
action schema is a JSON object; each project adapter validates its native action
space. Context declares source identity and action/observation spaces. Every
new episode begins at step zero and permits exactly the state variable and act
operation. Attach mode is deliberately unsupported by this shared utility.

`interaction-episode-scorer` independently reads AutoBenchTS's immutable result
and event snapshots, validates action/receipt/transition alignment, and computes
episode_return, episode_length, terminated, truncated and scope_limited. A terminal or scope-end
transition must be present, including its reward; interrupted evidence reports
insufficient coverage. It does not trust the Candidate to report its own return.
When a backend legitimately supplies no numeric rewards, episode_return alone
is insufficient; complete transition evidence can still establish length and
termination metrics. Missing rewards are never replaced by zeros.
TaskResult stores the decision and selected action; rewards remain environment
evidence. The scorer does not contact or replay the environment during rescoring.

This is a reusable domain package, not a new GymTS module or bundled project.
Observation projection and private info filtering belong to concrete adapters.
In-process trusted plugins are not an isolation boundary.

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
