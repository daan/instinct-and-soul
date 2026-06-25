#!/usr/bin/env bash
# Within-model variance batch: N hip + N wrist repeats of the same song/model.
# Each sim-spine run writes a fresh sim_creatures/<creature>/logs/<timestamp>/.
# The sim is deterministic, so all variance across repeats is the LLM's.
#
#   ./run_repeats.sh            # 5 hip + 5 wrist, lala, gemini
#   ./run_repeats.sh 10 gemini  # 10 each
#
# Afterwards, analyse the newest N of each in the midi-imu-analysis repo:
#   uv run python variance_analysis.py \
#     $(ls -dt sim_creatures/lala/logs/*/ | head -N) \
#     $(ls -dt sim_creatures/lala_wrist/logs/*/ | head -N) \
#     --wav kthstreet_gLH_sFM_cAll_d02_mLH_ch01_lala_001
set -e
cd "$(dirname "$0")"
N=${1:-5}
MODEL=${2:-gemini}
SONG=lala
for i in $(seq 1 "$N"); do
  echo "=== repeat $i/$N  HIP ==="
  uv run sim-spine sim_creatures/lala       --imu data/mocap/$SONG/imu_hips.jsonl --llm "$MODEL"
  echo "=== repeat $i/$N  WRIST ==="
  uv run sim-spine sim_creatures/lala_wrist --imu data/mocap/$SONG/imu_left.jsonl --llm "$MODEL"
done
echo "done: $N hip + $N wrist runs on $SONG / $MODEL"
