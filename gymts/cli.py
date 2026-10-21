"""JSON-first command line; optional YAML is a convenience extra."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from gymts import GymTS, GymTSError
from gymts.contracts import canonical_json


def load_config(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise GymTSError("unsupported_capability", "Install gymts[yaml] to read YAML; JSON needs no dependencies") from exc
        value = yaml.safe_load(text)
    else:
        value = json.loads(text)
    canonical_json(value)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gymts", description="GymTS experiments and AutoBenchTS evaluation")
    parser.add_argument("--store", default=".gymts", help="Local artifact and record directory")
    parser.add_argument("--data-home", help="Immutable data sources, datasets and benchmark directory")
    parser.add_argument("--cache-home", help="Local POSIX cache for verified resource objects")
    parser.add_argument("--integration", action="append", default=[], metavar="NAME",
                        help="Enable an optional integration explicitly (repeatable, e.g. chatts)")
    sub = parser.add_subparsers(dest="command", required=True)
    def data_arguments(child):
        child.add_argument("--source", required=True, help="Registered data source ID")
        child.add_argument("--source-revision", required=True, help="Fixed revision or immutable release label")
        child.add_argument("--source-config", default="default")
        child.add_argument("--dataset-id", required=True, help="Output dataset ID")
        child.add_argument("--config", default="default", help="Output dataset configuration")
        child.add_argument("--split", default="recorded")

    for command in ("plan", "validate", "run", "run-data", "evaluate", "score", "attach-outcomes"):
        child = sub.add_parser(command)
        child.add_argument("spec", help="JSON configuration (YAML with optional extra)")
        if command == "run-data":
            data_arguments(child)
        if command == "attach-outcomes":
            child.add_argument("--run-id", required=True)
        child.add_argument("--output", help="Save JSON result to this path")
    inspect = sub.add_parser("inspect", help="Read a persisted Run without executing it")
    inspect.add_argument("run_id")
    inspect.add_argument("--events", action="store_true", help="Include complete execution events")
    sub.add_parser("plugins", help="List exact registered component versions")
    experiments = sub.add_parser("experiments", help="Versioned experiment groups and stage attempts")
    experiment_sub = experiments.add_subparsers(dest="resource_command", required=True)
    group_register = experiment_sub.add_parser("register")
    group_register.add_argument("spec")
    group_register.add_argument("--output")
    for command in ("run", "info", "events"):
        child = experiment_sub.add_parser(command)
        child.add_argument("group_id")
        child.add_argument("--revision", required=True)
        child.add_argument("--output")
        if command == "run":
            child.add_argument("--retry-failed", action="store_true")
            child.add_argument("--rerun", action="append", default=[], metavar="STAGE_ID")
        if command == "events":
            child.add_argument("--after-seq", type=int, default=0)
    group_query = experiment_sub.add_parser("list")
    group_query.add_argument("--group-id")
    group_query.add_argument("--dataset-id")
    group_query.add_argument("--dataset-revision")
    group_query.add_argument("--status")
    group_query.add_argument("--output")
    recovery = experiment_sub.add_parser("recover")
    recovery.add_argument("attempt_id")
    recovery.add_argument("--reason", required=True)
    recovery.add_argument("--adopt-run", action="store_true")
    recovery.add_argument("--output")
    runs = sub.add_parser("runs", help="Query Run identities without expanding payloads")
    runs.add_argument("--group-id")
    runs.add_argument("--revision")
    runs.add_argument("--attempt-id")
    runs.add_argument("--dataset-id")
    runs.add_argument("--dataset-revision")
    runs.add_argument("--status")
    runs.add_argument("--output")
    sources = sub.add_parser("sources", help="Four-class data source definitions")
    source_sub = sources.add_subparsers(dest="resource_command", required=True)
    source_sub.add_parser("list")
    source_info = source_sub.add_parser("info")
    source_info.add_argument("source_id")
    source_info.add_argument("--revision", required=True)
    source_info.add_argument("--config", default="default")
    source_info.add_argument("--output")
    source_register = source_sub.add_parser("register")
    source_register.add_argument("spec")
    source_register.add_argument("--alias", action="append", default=[])
    source_register.add_argument("--output")
    datasets = sub.add_parser("datasets", help="EnvironmentTS source dataset resources")
    dataset_sub = datasets.add_subparsers(dest="resource_command", required=True)
    dataset_sub.add_parser("list")
    dataset_info = dataset_sub.add_parser("info")
    dataset_info.add_argument("dataset_id")
    dataset_info.add_argument("--revision", required=True)
    dataset_info.add_argument("--config", default="default")
    dataset_info.add_argument("--split", default="test")
    dataset_info.add_argument("--output")
    dataset_register = dataset_sub.add_parser("register")
    dataset_register.add_argument("spec")
    dataset_register.add_argument("--alias", action="append", default=[])
    dataset_register.add_argument("--output")
    dataset_capture = dataset_sub.add_parser("capture", help="Publish a sealed Run's environment data")
    dataset_capture.add_argument("run_id")
    data_arguments(dataset_capture)
    dataset_capture.add_argument("--output")
    dataset_publish = dataset_sub.add_parser("publish-build", help="Persist a built dataset beyond its original Run store")
    dataset_publish.add_argument("spec", help="JSON containing manifest, reader_ref and publication options")
    dataset_publish.add_argument("--output")
    autobench = sub.add_parser("autobench", help="AutoBenchTS reusable benchmark definitions")
    bench_sub = autobench.add_subparsers(dest="resource_command", required=True)
    bench_sub.add_parser("list")
    bench_register = bench_sub.add_parser("register")
    bench_register.add_argument("spec")
    bench_register.add_argument("--alias", action="append", default=[])
    bench_register.add_argument("--output")
    bench_resolve = bench_sub.add_parser("resolve")
    bench_resolve.add_argument("benchmark_id")
    bench_resolve.add_argument("--revision", required=True)
    bench_resolve.add_argument("--candidate", action="append", required=True,
                               help="JSON candidate_id/spec object (repeat for several candidates)")
    bench_resolve.add_argument("--purpose", default="regression",
                               choices=("development", "regression", "acceptance"))
    bench_resolve.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        with GymTS(root=args.store, integrations=args.integration,
                   data_home=args.data_home, cache_home=args.cache_home) as gym:
            if args.command == "plugins":
                value = {kind: getattr(gym.registries, kind).manifests()
                         for kind in ("environments", "tasks", "candidates", "scorers")}
            elif args.command == "experiments":
                organization = gym.experiments
                if args.resource_command == "register":
                    value = organization.register(load_config(args.spec))
                elif args.resource_command == "run":
                    value = organization.execute(args.group_id, revision=args.revision,
                                                 retry_failed=args.retry_failed, rerun=args.rerun)
                elif args.resource_command == "info":
                    value = organization.inspect(args.group_id, revision=args.revision)
                elif args.resource_command == "list":
                    value = {"experiments": organization.query(group_id=args.group_id, dataset_id=args.dataset_id,
                             dataset_revision=args.dataset_revision, status=args.status)}
                elif args.resource_command == "events":
                    value = {"events": organization.events(args.group_id, revision=args.revision, after_seq=args.after_seq)}
                else:
                    value = organization.recover(args.attempt_id, reason=args.reason, adopt_run=args.adopt_run)
            elif args.command == "runs":
                value = {"runs": gym.records.list_runs(group_id=args.group_id, revision=args.revision,
                    attempt_id=args.attempt_id, dataset_id=args.dataset_id, dataset_revision=args.dataset_revision,
                    status=args.status)}
            elif args.command == "sources":
                catalog = gym.environment_ts.datasets
                if args.resource_command == "list":
                    value = {"sources": catalog.list_sources()}
                elif args.resource_command == "register":
                    value = catalog.register_source(load_config(args.spec), aliases=args.alias)
                else:
                    value = catalog.load_source(args.source_id, revision=args.revision, config=args.config)
            elif args.command == "datasets":
                catalog = gym.environment_ts.datasets
                if args.resource_command == "list":
                    value = {"datasets": catalog.list_datasets()}
                elif args.resource_command == "register":
                    value = catalog.register_dataset(load_config(args.spec), aliases=args.alias)
                elif args.resource_command == "capture":
                    value = catalog.capture_run(args.run_id, source_id=args.source,
                        revision=args.source_revision, source_config=args.source_config,
                        dataset_id=args.dataset_id, config=args.config, split=args.split)
                elif args.resource_command == "publish-build":
                    publication = load_config(args.spec)
                    manifest = publication.pop("manifest")
                    value = catalog.publish_build(manifest, **publication)
                else:
                    value = catalog.load_dataset(args.dataset_id, revision=args.revision,
                        config=args.config, split=args.split).info
            elif args.command == "autobench":
                if args.resource_command == "list":
                    value = {"benchmarks": gym.autobench.list_benchmarks()}
                elif args.resource_command == "register":
                    value = gym.autobench.register_benchmark(load_config(args.spec), aliases=args.alias)
                else:
                    value = gym.autobench.resolve_benchmark(args.benchmark_id, revision=args.revision,
                        candidates=[load_config(path) for path in args.candidate], purpose=args.purpose)
            elif args.command == "inspect":
                value = gym.records.get_run(args.run_id)
                if not args.events:
                    value.pop("events", None)
                    value.pop("event_refs", None)
            else:
                spec = load_config(args.spec)
                if args.command == "plan":
                    value = gym.plan(spec)
                elif args.command == "validate":
                    value = gym.validate(spec)
                elif args.command == "run":
                    value = gym.run(spec)
                elif args.command == "run-data":
                    value = gym.run_data(spec, source_id=args.source, revision=args.source_revision,
                        source_config=args.source_config, dataset_id=args.dataset_id,
                        config=args.config, split=args.split)
                elif args.command == "evaluate":
                    value = gym.autobench.evaluate(spec)
                elif args.command == "score":
                    value = gym.autobench.score(spec)
                else:
                    value = gym.records.attach_outcomes(args.run_id, spec)
            rendered = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
            if getattr(args, "output", None):
                output = Path(args.output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered + "\n", encoding="utf-8")
            print(rendered)
            if args.command == "validate" and not value["valid"]:
                return 2
            if value.get("status") in ("failed", "cancelled") or value.get("run", {}).get("status") in ("failed", "cancelled"):
                return 1
            return 0
    except GymTSError as error:
        print(json.dumps({"error": error.info}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"error": {"code": "invalid_config", "message": f"Could not read configuration: {type(error).__name__}"}}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
