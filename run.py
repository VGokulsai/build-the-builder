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
from builder import llm
from builder.llm import CALLS


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("task", help="task JSON: id, description, tools[]")
    p.add_argument("--rounds", type=int, default=4, help="revise rounds")
    p.add_argument("--train", type=int, default=4, help="test customers used for improving")
    p.add_argument("--val", type=int, default=3, help="fresh customers used for picking the winner")
    p.add_argument("--k", type=int, default=2, help="plays per customer; the worst one counts")
    p.add_argument("--minutes", type=float, default=None,
                   help="time budget for this task; stops early and delivers the best agent so far")
    p.add_argument("--out", default="out")
    p.add_argument("--log", default=None, help="write one JSON line per model call here (timing, outcome)")
    a = p.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)   # progress shows up live even when redirected to a file
    if a.log:
        llm.CALL_LOG = a.log

    with open(a.task, encoding="utf-8") as f:
        task = json.load(f)
    # a task without an id is named after its file, so two such tasks never overwrite each other
    task["id"] = str(task.get("id") or os.path.splitext(os.path.basename(a.task))[0])
    spec, report = core.build(task, rounds=a.rounds, n_train=a.train, n_val=a.val, k=a.k, minutes=a.minutes)
    report["model_calls"] = CALLS["n"]
    report["provider"] = os.environ.get("LLM_PROVIDER", "stub")

    out = os.path.join(a.out, task["id"])
    os.makedirs(out, exist_ok=True)
    for name, data in (("agent.json", platform.export(spec, task)), ("report.json", report)):
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
    print("wrote %s (best round %d, train %s, val %s, fallbacks %s, %d model calls)" % (
        out, report["best_round"], core._fmt(report["train"]), core._fmt(report["val"]),
        [k for k, v in report["fallbacks"].items() if v] or "none", CALLS["n"]))
    return spec, report


if __name__ == "__main__":
    main()
