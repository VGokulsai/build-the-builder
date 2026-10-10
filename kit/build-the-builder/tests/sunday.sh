#!/usr/bin/env bash
# Tests that need no Claude: run them before the limit resets, read the results after.
#   cd /c/Users/sridh/build-the-builder/kit/build-the-builder && bash tests/sunday.sh
# Writes everything to results/sunday.txt (about an hour; one simulation at a time).
cd "$(dirname "$0")/.." || exit 1
source env.sh
PY="py -3"; command -v py >/dev/null || PY=python3
OUT=results/sunday.txt
echo "started $(date)" > "$OUT"
run() { echo -e "\n===== $*" | tee -a "$OUT"; $PY tools/run_cases.py "$@" 2>&1 | grep -E "^(PASS|FAIL)|^ +- |^[0-9]+ / " | tee -a "$OUT"; }
# 1. the agent the builder made alone for multi-product Brief D
run f4d41e7f-2c52-4315-b5dc-6a6a46bedace --cases briefs-test/cases-d.json --reps 3 --out results/sun-d.json
# 2. reference agents against the talking styles of the final customers
for s in pieces corrects talkative asks_back in_words; do
  run eb44e825-be41-4dc4-974c-74a88a4d54a9 --brief B --style "$s" --out "results/sun-b-$s.json"
done
for s in pieces corrects in_words; do
  run a7da0371-40d9-4c25-bd78-116fc7f7de69 --brief A --style "$s" --out "results/sun-a-$s.json"
done
echo -e "\nfinished $(date)" | tee -a "$OUT"
