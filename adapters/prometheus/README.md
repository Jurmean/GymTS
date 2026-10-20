# gymts-prometheus

Independent read-only `prometheus-live` Environment provider. GymTS core owns
execution and evidence; PromQL, HTTP, labels, float conversion and source timing
live in this separately installed adapter. It owns no model, Task or Scorer.

```bash
python -m pip install /path/to/Jurmean-GymTS /path/to/Jurmean-GymTS/adapters/prometheus
python -I examples/live_demo.py --endpoint http://127.0.0.1:9090 --store /tmp/live-runs
```

Enable explicitly with `GymTS(..., integrations=('prometheus',))`. The source
connection specifies base_url, named queries `{variable: {expression, labels}}`,
optional timeout_seconds and token_env (an environment-variable *name*). Mapping
declares variable units; options declare step_seconds and an entity. Credentials
are read on invocation and never written to requests or results. Redirects are
rejected. Configure a bounded expression and exact label set for each variable;
multiple matching series fail, rather than silently selecting the first one.

Only `start.mode='attach'` and `execution.seed=null` are supported. This adapter
cannot reset a real service or promise a simulated seed. Each Run receives a
live, still-open wall-time scope; historical closed intervals should be frozen
as static resources and replayed. Native `/api/v1/query_range` has an inclusive
end; returned samples are filtered to GymTS half-open windows. Polling before a
whole requested window is mature returns waiting without moving the cursor or
visibility. Empty mature windows advance coverage. Non-finite sample values
become explicit invalid nulls; raw responses remain evidence. Native histograms
require another representation adapter and are rejected.

Sample timestamps and actual HTTP receipt availability are distinct. Prometheus
range samples are PromQL evaluation values and can include lookback; this adapter
does not claim to know original ingestion time. The configured query fixes what
is observed. Queries from the Task can only read already delivered immutable
history for each captured variable and interval (including observed empty windows),
cannot submit arbitrary PromQL, and never change the main cursor or
visibility. The adapter exposes no write/control operation. Live runs of different
candidates need explicitly arranged observation windows or a common frozen replay;
sequential execution cannot replay the same real-world time.

Plan/discovery are pure. The actual Run opens HTTP and verifies server build info,
records requests before dispatch, retains raw responses and failures in CAS, and
does not retry reads automatically. A live source revision identifies configured
deployment/build claims, not immutable future data. Sealed observations and their
receipt times are the evidence. Finish releases only this adapter's client state;
it never stops or resets an attached server.

`examples/native_server_demo.py --output /tmp/new-validation --prometheus-binary
/path/to/prometheus` starts a real Prometheus process scraping a localhost exporter.
It uses existing reference forecast components by configuration to verify input
compatibility, then supplies an explicit independent fixture reference (42), scores
and re-scores sealed output while network access is disabled. Model/scoring logic
is not added to this provider or to core. This is a local integration fixture,
not a production-testbed or forecasting-quality result. The reference Task uses
sample time for its decision timestamp, which precedes HTTP receipt availability;
this example does not establish causal online prediction. Server termination is
performed only by this example's owning harness after proving GymTS left it alive.

Tests use clearly identified protocol fixtures; the native example separately
requires a real Prometheus binary. Wheel/sdist contain no server binary or data.

Primary references: [Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/)
and [installation](https://prometheus.io/docs/prometheus/latest/installation/).

## License

GymTS-owned code in this package is licensed under the [MIT License](LICENSE).
Third-party libraries, upstream projects, datasets, model weights and services
retain their own licenses and terms; this package does not relicense them.
