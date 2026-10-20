#!/usr/bin/env bash
# A fresh local experiment: official GSM8K + genuine ChatTS generation → GRPO.
set -euo pipefail
GYMTS_RL_PYTHON="${GYMTS_RL_PYTHON:-python3}"
GYMTS_RL_OUTPUT="${GYMTS_RL_OUTPUT:-/tmp/gymts-rl-$(date +%Y%m%d-%H%M%S)}"
GYMTS_RL_MODEL="${GYMTS_RL_MODEL:-/zzr/models/Qwen2.5-7B-I}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
"$GYMTS_RL_PYTHON" -B -m gymts_rl.cli --store "$GYMTS_RL_OUTPUT/records" prepare \
  --output "$GYMTS_RL_OUTPUT/data" --gsm8k-train 16 --gsm8k-eval 4 \
  --chatts-train 8 --chatts-eval 4 --sequence-length 64
"$GYMTS_RL_PYTHON" -B -m gymts_rl.cli --store "$GYMTS_RL_OUTPUT/records" train \
  --data "$GYMTS_RL_OUTPUT/data" --model "$GYMTS_RL_MODEL" --family text \
  --device cuda:0 --dtype bfloat16 --output "$GYMTS_RL_OUTPUT/training" \
  --steps "${GYMTS_RL_STEPS:-3}" --generations 4 --groups-per-step 2 --max-new-tokens 768
