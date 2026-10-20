"""Installed-package example; complete746 coverage, no model service or gold access."""
import argparse
import json
from gymts import GymTS
from gymts_bench_tsqa.benchmark import first_choice_candidate

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-home',required=True)
parser.add_argument('--root',default='/tmp/gymts-tsqa-full746')
args=parser.parse_args()
with GymTS(args.root,data_home=args.data_home,cache_home='/tmp/gymts-tsqa-cache',integrations=('bench-tsqa',)) as gym:
    spec=gym.autobench.resolve_benchmark('local/tsexam-mcq',revision='1.0.0',
        candidates=[first_choice_candidate()],purpose='regression')
    print(json.dumps(gym.autobench.evaluate(spec),ensure_ascii=False,indent=2))
