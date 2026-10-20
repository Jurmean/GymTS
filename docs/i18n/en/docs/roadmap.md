# Roadmap and framework evolution

The roadmap describes integration and validation directions, not promised release dates, owners, or secured resources. See [project status](project-status.md) for current capabilities and the [historical roadmap review](enterprise-platform-roadmap.md) for the full enterprise platform proposal.

## Continuing principles

1. Integrate real projects, preserve their native semantics first, and expose public contracts through independent adapters.
2. EnvironmentTS retains execution/evidence; AutoBenchTS retains evaluation. Project formats, models, and domain scoring remain external.
3. Record the unmet requirement, why an adapter cannot solve it, compatibility, and existing-project regressions for every core change.
4. Periodically freeze the core and require new projects to run, seal evidence, evaluate independently, and rescore the same Runs; judge generality through actual compatibility.
5. Prefer adapting existing training, Agent, simulation, and operational infrastructure when reusable implementations exist.

## Future directions and acceptance conditions

| Direction | Incremental scope | Completion evidence |
| --- | --- | --- |
| Continuous independent integration | New sources, Tasks, methods, and Scorers without project-name branches | Real runs on a fixed core, rejected invalid combinations, independent installation/removal, and original-Run rescoring |
| Agent tool workflows | Preserve native Agent loops and connect replaceable tool providers | Real tool selection → invocation → consumption → continued reasoning; evidence for environment permissions, costs, failures, and every call |
| Resource collaboration and sharing | Remote resource indexes, reviewed publication, large-scale reading, more domain projections | Immutable identities, authorized uses, concurrent publication, and cross-machine replay; external adapters still handle formats/domains |
| Runtime boundaries | External workers, isolation, forced interruption, cancellation, recovery, resource governance | Negative tests for untrusted plugins and resource exhaustion, failure recovery, complete evidence, and real multi-team pilots |
| Training backends and profiles | Reuse more backends and multi-round export for actual needs | Fixed snapshots, complete mask/reward lineage, real updates, checkpoint loading in a new process, independent evaluation |
| Production live testbeds | Integrate authentication, deployment identity, and permitted operations for each target system | Separate read/write acceptance, no resend of unknown side effects, no accidental closure of attached resources |

## Proposing changes

Start with a concrete workflow or minimal failing case and identify the current interface that cannot express it. If only field formats, algorithms, codecs, or scoring rules differ, create or update an independent adapter first. Core changes require contract versions and migration plans; draft fields must not be promoted as implemented APIs. Follow the checks in [contributing](../CONTRIBUTING.md) and [adapter development](adapter-development.md).
