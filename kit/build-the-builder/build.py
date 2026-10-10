"""Our builder. One command: brief files in, a phone agent on Freya out.

    python3 build.py briefs/brief-a.md                         # slot "brief-a", tool API tools/openapi.json
    python3 build.py briefs/brief-a.md briefs/brief-b.md       # B builds on A: pass both, the last names the slot
    python3 build.py final/brief-x.md --api final/openapi-x.json

Claude (Claude Agent SDK) runs the skill .claude/skills/collections-builder, which writes the agent with
kitlib, tests its code locally, saves and publishes it, checks it on Freya and exports it.
Needs FREYA_API_KEY and FREYA_BANK_TEAM_KEY (env.sh) and a Claude login or ANTHROPIC_API_KEY.

Trace: traces/<slot>-<start>.jsonl has every message of the run; traces/<slot>-<start>.txt is the plain
summary the rules ask for (start and end time, each model call with its model and purpose, what was
created on Freya, every test run).
"""
import argparse
import asyncio
import dataclasses
import json
import os
import pathlib
import sys
import time

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolUseBlock, query

KIT = pathlib.Path(__file__).resolve().parent
LIMIT_S = 30 * 60          # the rules: one builder run may take 30 minutes at most, tests included


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


async def run(briefs, api, slot, model, practice):
    started = time.time()
    tag = slot + "-" + time.strftime("%Y%m%d-%H%M%S")
    (KIT / "traces").mkdir(exist_ok=True)
    jl, txt = KIT / "traces" / (tag + ".jsonl"), KIT / "traces" / (tag + ".txt")
    summary = ["builder trace for slot %s" % slot, "start: " + stamp(), "briefs: " + ", ".join(briefs),
               "tool API: " + api, "builder model: " + model, ""]
    env = {"BASH_DEFAULT_TIMEOUT_MS": "900000", "BASH_MAX_TIMEOUT_MS": "1200000",
           "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1", "PYTHON": sys.executable,
           "BUILD_SLOT": slot, "BUILD_API": api, "BUILD_DEADLINE": str(int(started + LIMIT_S - 120))}
    options = ClaudeAgentOptions(
        cwd=KIT, model=model, skills=["collections-builder"], setting_sources=["project"],
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"], permission_mode="dontAsk",
        mcp_servers={}, extra_args={"strict-mcp-config": None},   # no connectors from the user's account
        max_turns=200, env=env)
    prompt = ("Use the collections-builder skill to build the phone agent.\n"
              "Brief files, in order (later ones build on earlier ones): %s\n"
              "Tool API file: %s\nSlot: %s\nPractice customers: %s\n"
              "Python: run every script with the interpreter in $PYTHON.\n"
              "Hard deadline: unix time %s. Finish and export before it."
              % (" ".join(briefs), api, slot,
                 ("run $PYTHON tools/run_cases.py <agent_id> " + practice) if practice else "none (the brief has no practice customers)",
                 env["BUILD_DEADLINE"]))
    turn = 0
    with jl.open("w", encoding="utf-8") as out:
        out.write(json.dumps({"start": stamp(), "briefs": briefs, "api": api, "slot": slot, "model": model}) + "\n")
        async for m in query(prompt=prompt, options=options):
            out.write(json.dumps({"type": type(m).__name__, **dataclasses.asdict(m)}, default=str) + "\n")
            out.flush()
            if isinstance(m, AssistantMessage):
                turn += 1
                purpose, tools = "", []
                for b in m.content:
                    if isinstance(b, TextBlock):
                        print(b.text, flush=True)
                        purpose = purpose or " ".join(b.text.split())[:120]
                    elif isinstance(b, ToolUseBlock):
                        line = (b.input.get("command") or b.input.get("file_path") or b.input.get("pattern") or "")
                        tools.append("%s %s" % (b.name, " ".join(str(line).split())[:110]))
                        print("  [%s] %s" % (b.name, str(line)[:120]), flush=True)
                summary.append("%s model call %d (%s): %s%s" % (time.strftime("%H:%M:%S"), turn, getattr(m, "model", model),
                                                               purpose or "tool use", "" if not tools else " | " + "; ".join(tools)))
            elif isinstance(m, ResultMessage):
                summary.append("")
                summary.append("result: %d turns, %.0f s, cost $%.2f" % (m.num_turns, m.duration_ms / 1000, m.total_cost_usd or 0))
                if m.result:
                    summary.append("final message: " + m.result.strip())
            if time.time() - started > LIMIT_S:
                summary.append("STOPPED: the 30-minute limit was reached")
                break
    summary.append("end: " + stamp())
    agents = KIT / ".freya-agents.json"
    if agents.exists():
        summary.append("created/updated on Freya: " + json.dumps(json.load(open(agents)).get(slot)))
    log = KIT / "results" / "log.jsonl"
    if log.exists():
        runs = [l for l in log.read_text().splitlines() if json.loads(l)["at"] >= time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started))]
        summary += ["tests run on its own agent:"] + ["  " + r for r in runs]
    txt.write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\ntrace: %s\n       %s\nbuild time %.0f s" % (txt, jl, time.time() - started))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("briefs", nargs="+")
    ap.add_argument("--api", default="tools/openapi.json")
    ap.add_argument("--slot", help="defaults to the last brief's file name")
    ap.add_argument("--model", default=os.environ.get("BUILDER_MODEL", "claude-opus-5-5"))
    ap.add_argument("--practice", help='arguments for tools/run_cases.py when the brief has practice customers, e.g. "--brief A" or "--cases briefs-test/cases-c.json"')
    a = ap.parse_args()
    slot = a.slot or pathlib.Path(a.briefs[-1]).stem
    asyncio.run(run(a.briefs, a.api, slot, a.model, a.practice))


if __name__ == "__main__":
    main()
