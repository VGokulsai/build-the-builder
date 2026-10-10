"""Print one call as a readable timeline: what each side said, node changes, tool calls and
results, routing decisions and engine errors. The fastest way to see why a customer failed.

    py -3 kitlib/why.py <call_id>
    py -3 kitlib/why.py results/run.json [PUB-03,PUB-07]     # every failed case of a run_cases --out file
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import freya  # noqa: E402


def timeline(call_id, out=print):
    call = freya.get_call(call_id)
    out("== call %s ended: %s" % (call_id, call.get("endedReason")))
    for m in call.get("messages", []):
        if m.get("role") != "system":
            out("%-5s %s   [%s]" % (m["role"].upper()[:5], (m.get("message") or "").replace("\n", " "), m.get("nodeId")))
            continue
        try:
            e = json.loads(m["message"])
        except (ValueError, TypeError):
            out("SYS   " + str(m.get("message"))[:200])
            continue
        ev = e.get("event")
        if ev == "node_enter":
            out("NODE  %s -> %s (%s)" % (e.get("from_node"), e.get("node"), str(e.get("reason"))[:90]))
        elif ev == "function_call_start":
            args = e.get("args") or {}
            out("CALL  %s %s" % (e.get("function"), json.dumps(args.get("body", args))[:200]))
        elif ev == "function_call_complete":
            out("RES   %s %s" % (e.get("function"), json.dumps((e.get("result") or {}).get("data", e.get("result")))[:300]))
        elif ev == "error":
            out("ERROR %s" % json.dumps(e)[:300])
    return call


if __name__ == "__main__":
    arg = sys.argv[1]
    if arg.endswith(".json"):
        run = json.load(open(arg))
        only = sys.argv[2].split(",") if len(sys.argv) > 2 else None
        for row in run["rows"]:
            if (only and row["id"] in only) or (not only and not row["pass"]):
                print("\n######## %s  %s" % (row["id"], row["failed"]))
                if row.get("call_id"):
                    timeline(row["call_id"])
    else:
        timeline(arg)
