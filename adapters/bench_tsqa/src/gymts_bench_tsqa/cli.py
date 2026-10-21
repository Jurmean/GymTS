"""Explicit local resource import and complete benchmark integration checks."""
import argparse
import json
from pathlib import Path


def main():
    from gymts import GymTS
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('import','list','evaluate'))
    parser.add_argument('--data-home',required=True)
    parser.add_argument('--cache-home',default='/tmp/gymts-tsqa-resource-cache')
    parser.add_argument('--root',default='/tmp/gymts-tsqa-records')
    parser.add_argument('--attachments')
    parser.add_argument('--benchmark',default='local/tsexam-mcq')
    parser.add_argument('--revision',default='2.0.0')
    parser.add_argument('--report')
    args=parser.parse_args()
    with GymTS(args.root,data_home=args.data_home,cache_home=args.cache_home,integrations=('bench-tsqa',)) as gym:
        if args.command=='import':
            if not args.attachments:
                parser.error('--attachments is required for import')
            from .importer import import_attachments
            result=import_attachments(gym,args.attachments,alias=args.revision)
        elif args.command=='list':
            result={'datasets':gym.environment_ts.datasets.list_datasets(),'benchmarks':gym.autobench.list_benchmarks()}
        else:
            from .benchmark import first_choice_candidate
            spec=gym.autobench.resolve_benchmark(args.benchmark,revision=args.revision,
                candidates=[first_choice_candidate()],purpose='regression')
            result=gym.autobench.evaluate(spec)
        encoded=json.dumps(result,ensure_ascii=False,indent=2)
        if args.report:
            Path(args.report).write_text(encoded+'\n')
        print(encoded)


if __name__=='__main__':
    main()
