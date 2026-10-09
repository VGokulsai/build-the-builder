"""Build an agent for one task. The command the judges run to reproduce us.

    python run.py tasks/bank_card_freeze.json --rounds 3 --scenarios 4

Writes out/<task id>/agent.json (the agent, in the platform's format) and
out/<task id>/report.json (every round's score and failures, the held-out
score, and how many model calls it took).
"""
import argparse
import json
import os
import sys

from builder import core, platform
from builder.llm import CALLS


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("task", help="task JSON: id, description, tools[]")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--scenarios", type=int, default=4)
    p.add_argument("--out", default="out")
    a = p.parse_args(argv)

    task = json.load(open(a.task, encoding="utf-8"))
    spec, report = core.build(task, rounds=a.rounds, n_scenarios=a.scenarios)
    report["model_calls"] = CALLS["n"]
    report["provider"] = os.environ.get("LLM_PROVIDER", "stub")

    out = os.path.join(a.out, task.get("id", "task"))
    os.makedirs(out, exist_ok=True)
    json.dump(platform.export(spec, task), open(os.path.join(out, "agent.json"), "w", encoding="utf-8"), indent=1)
    json.dump(report, open(os.path.join(out, "report.json"), "w", encoding="utf-8"), indent=1)
    print("wrote %s (best round %d, held-out %.1f, %d model calls)" % (out, report["best_round"], report["held_out"], CALLS["n"]))
    return spec, report


if __name__ == "__main__":
    sys.exit(main() and 0)
