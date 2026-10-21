"""Domain evidence declarations; no AReaL implementation enters GymTS core."""
from gymts.plugin_support import component

PINNED_REVISION = "3b93679888e9f4929f6f155f13c6a286a62dfd72"
UPSTREAM_URL = "https://github.com/areal-project/AReaL"
PARAMS = "gymts.areal/candidate-params/1"
ROLLOUT = "gymts.areal/native-tir-rollout/1"
EVENT = "gymts.areal/native-event/1"
SHARD = "gymts.areal/native-tir-training-shard/2"
IDENTITY = "gymts.areal/policy-identity/1"
TOKENIZER = "gymts.areal/tokenizer/1"
TEMPLATE = "gymts.areal/chat-template/1"
REWARD_AUDIT = "gymts.areal/reward-audit/1"
BUILDER = component("gymts.areal.sealed-tir-builder", "2.0.0")
CODEC = component("areal.boxed-to-verifiable-qa", "2.0.0")
PROMPT_PROJECTION = component("areal.public-calculator-verification", "3.0.0")
MASK = component("areal.native-tir-prompt-tool-mask", PINNED_REVISION)


def implementation_ref():
    return component("areal", PINNED_REVISION)
