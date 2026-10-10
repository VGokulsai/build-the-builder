"""Build an agent for every task in a folder: the command for the judges' unseen tasks.

    python run_all.py tasks/ --minutes 20 --out out/

Each task runs in its own process with its own time budget, so one task that crashes
or hangs cannot take the others down. Writes out/<task id>/agent.json per task and
out/summary.json saying, for every task, whether an agent was written.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("folder", help="folder of task JSON files")
    p.add_argument("--minutes", type=float, default=20, help="time budget per task")
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--train", type=int, default=4)
    p.add_argument("--val", type=int, default=3)
    p.add_argument("--k", type=int, default=2)
    p.add_argument("--out", default="out")
    a = p.parse_args(argv)

    summary = {}
    for path in sorted(glob.glob(os.path.join(a.folder, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                task_id = str(json.load(f).get("id") or os.path.splitext(os.path.basename(path))[0])
        except ValueError as e:
            summary[path] = {"agent": False, "error": "not valid JSON: %s" % e}
            continue
        cmd = [sys.executable, os.path.join(HERE, "run.py"), path, "--minutes", str(a.minutes), "--rounds", str(a.rounds),
               "--train", str(a.train), "--val", str(a.val), "--k", str(a.k), "--out", a.out]
        try:
            # a hard stop a little past the task's own budget, in case anything ignores it
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=a.minutes * 60 + 120,
                               encoding="utf-8", errors="replace")
            tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
            status = {"exit": r.returncode, "last_line": tail[0][:300]}
        except subprocess.TimeoutExpired:
            status = {"exit": None, "last_line": "killed: ran past %.0f minutes" % (a.minutes + 2)}
        agent = os.path.join(a.out, task_id, "agent.json")
        summary[path] = dict(status, task_id=task_id, agent=os.path.exists(agent))
        print("%-40s agent=%s  %s" % (task_id, summary[path]["agent"], status["last_line"]), flush=True)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    missing = [k for k, v in summary.items() if not v["agent"]]
    print("%d of %d tasks have an agent%s" % (len(summary) - len(missing), len(summary),
                                               "" if not missing else "; MISSING: %s" % missing))
    return summary


if __name__ == "__main__":
    main()
