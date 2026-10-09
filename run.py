"""Build an agent for one task. The command the judges run to reproduce us.

    python run.py tasks/bank_card_freeze.json --rounds 4 --train 4 --val 3 --k 2

Writes out/<task id>/agent.json (the agent, in the platform's format) and
out/<task id>/report.json (the rules it extracted, every candidate's scores and
failures, the validation scores, and how many model calls it took).
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
    p.add_argument("--rounds", type=int, default=4, help="revise rounds")
    p.add_argument("--train", type=int, default=4, help="test customers used for improving")
    p.add_argument("--val", type=int, default=3, help="fresh customers used for picking the winner")
    p.add_argument("--k", type=int, default=2, help="plays per customer; the worst one counts")
    p.add_argument("--out", default="out")
    a = p.parse_args(argv)

    task = json.load(open(a.task, encoding="utf-8"))
    spec, report = core.build(task, rounds=a.rounds, n_train=a.train, n_val=a.val, k=a.k)
    report["model_calls"] = CALLS["n"]
    report["provider"] = os.environ.get("LLM_PROVIDER", "stub")

    out = os.path.join(a.out, task.get("id", "task"))
    os.makedirs(out, exist_ok=True)
    json.dump(platform.export(spec, task), open(os.path.join(out, "agent.json"), "w", encoding="utf-8"), indent=1)
    json.dump(report, open(os.path.join(out, "report.json"), "w", encoding="utf-8"), indent=1)
    print("wrote %s (best round %d, train %.2f, val %s, %d model calls)" % (
        out, report["best_round"], report["train"], report["val"], CALLS["n"]))
    return spec, report


if __name__ == "__main__":
    sys.exit(main() and 0)
