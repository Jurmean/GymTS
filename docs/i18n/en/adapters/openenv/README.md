# GymTS OpenEnv adapter

An independent environment source for an external OpenEnv server. GymTS core
does not import OpenEnv. `gymts-interaction` supplies a neutral JSON control
Task, Candidate examples and an independent episode Scorer; it contains no
Gymnasium or OpenEnv implementation.

The adapter uses the **official `GenericEnvClient(mode="simulation")`** SDK and
one persistent `/ws` connection per Run. HTTP `/reset` and `/step` are stateless
in current OpenEnv and are deliberately not used. Current upstream Echo's
`EchoEnv` class is an MCP production client; using it would conflate the
production tool API with the simulation reward/done loop.

## Install and run

The acceptance source is official OpenEnv commit
`f2b00027b63242df33fbbf3af693bbc7cbfa9955` (`0.9.1.dev0`, Python >= 3.10).
Install into a separate virtual environment:

```sh
git clone https://github.com/huggingface/OpenEnv.git /tmp/OpenEnv
git -C /tmp/OpenEnv checkout f2b00027b63242df33fbbf3af693bbc7cbfa9955
python -m pip install /tmp/OpenEnv /tmp/OpenEnv/envs/echo_env /tmp/OpenEnv/envs/connect4_env
python -m pip install . ./adapters/interaction ./adapters/openenv
python adapters/openenv/examples/echo_roundtrip.py --owned-local-echo --root /tmp/gymts-openenv-native
python adapters/openenv/examples/echo_roundtrip.py --owned-local-server --environment connect4 --root /tmp/gymts-openenv-connect4
python adapters/openenv/examples/fault_roundtrip.py --root /tmp/gymts-openenv-faults
```

The example starts the real upstream Echo server, executes three real MCP
`echo_message` actions through the simulation WS, independently scores the
sealed events with AutoBenchTS, and rescores the same Runs. It verifies the
host is still alive after the adapter closes its connection. The launcher then
terminates only the local process it created.

For an existing host use `--base-url http://host:port`. The caller supplies a
fixed SDK version and deployment identity in EnvironmentSpec. A generic remote
server does not attest its code/image identity: the evidence explicitly labels
the supplied identity as declared, rather than claiming remote verification.
Private endpoint authentication needs an explicit credential provider; URLs
with userinfo/query/fragment and non-null credential refs are rejected.

## Semantics and evidence

- New Run means a **new WS session** on an attached host, then exactly one reset.
  The session is owned by the Run; the host is never owned or killed by this
  adapter. Existing sessions cannot be attached or resumed through this API.
- Pure planning reads configuration only. SDK import and connection occur at
  execution start. Exact configured SDK version is checked before native I/O.
- Task/Candidate action is a JSON object; no domain action coercion is applied.
  The Environment caches each returned transition. `observe` consumes the
  cache and never repeats a native step.
- Every reset/state/step request and response envelope is committed to CAS,
  including server error envelopes. Timeouts/connection errors make the
  session uncertain, produce an unknown operation receipt where applicable,
  and forbid resending or reconnecting into a fresh remote environment.
- OpenEnv has one `done` flag. Its lossless original value remains in evidence
  as `backend_done`; it closes the episode without guessing a terminated versus
  truncated cause. Unknown cause means those cause metrics are insufficient,
  while return/length can still be scored. Execution-scope truncation is separate.
- Generic seed enforcement is unsupported. Official Echo accepts but ignores
  seeds, so non-null execution seeds are rejected during planning. A terminal
  initial reset is currently unsupported and fails explicitly.
- Missing native rewards remain `null`; the episode Scorer reports insufficient
  evidence instead of inventing zero. Current MCP Echo returns null rewards,
  so its example requests length and scope-limitation metrics only. Native
  truncated is kept separate from the experiment's own scope limit. Official Connect4
  reaches native done after seven real moves and supplies reward 1; its example
  evaluates return and length. Both are integration checks, not production task
  benchmarks or proof of an autonomous agent's capability.

Official references: [OpenEnv source](https://github.com/huggingface/OpenEnv),
[Generic client](https://github.com/huggingface/OpenEnv/blob/f2b00027b63242df33fbbf3af693bbc7cbfa9955/src/openenv/core/generic_client.py),
[WebSocket SDK](https://github.com/huggingface/OpenEnv/blob/f2b00027b63242df33fbbf3af693bbc7cbfa9955/src/openenv/core/env_client.py),
[Echo server](https://github.com/huggingface/OpenEnv/blob/f2b00027b63242df33fbbf3af693bbc7cbfa9955/envs/echo_env/server/app.py).

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
