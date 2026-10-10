"""End-to-end checks with the stub model: py -3 test_builder.py

The stub grades rev 0 = 0 (breaks a critical rule), rev 1 = 1.0, rev 2+ = 0.75,
so the builder must keep the best agent, not the latest one.
"""
import json
import os
import tempfile

os.environ["LLM_PROVIDER"] = "stub"

import run  # noqa: E402
from builder import core  # noqa: E402

out = tempfile.mkdtemp()
spec, report = run.main(["tasks/bank_card_freeze.json", "--rounds", "4", "--train", "3", "--val", "2", "--k", "2", "--out", out])

scores = [c["score"] for c in report["pool"]]
assert [round(s, 6) for s in scores] == [0.1, 1.0, 0.75, 0.75], scores           # a critical breach is capped at 0.2 x its share; partial misses score in between
assert report["best_round"] == 1 and "rev 1" in spec["system_prompt"], (report["best_round"], spec["system_prompt"])
assert report["val"] == 1.0, report["val"]                   # the winner was re-scored on fresh customers
assert sum(r["critical"] for r in report["rules"]) == 2, report["rules"]

agent = json.load(open(os.path.join(out, "bank_card_freeze", "agent.json"), encoding="utf-8"))
assert "Phone style:" in agent["prompt"] and core.VOICE_RULES[2] in agent["prompt"], "phone rules missing"

# a step that blows up mid-run must not lose the agents already built
real_revise, calls = core.revise, {"n": 0}
def flaky_revise(*a, **kw):
    calls["n"] += 1
    if calls["n"] == 2:
        raise ConnectionError("simulated outage")
    return real_revise(*a, **kw)
core.revise = flaky_revise
spec2, report2 = core.build(json.load(open("tasks/bank_card_freeze.json")), rounds=4, n_train=2, n_val=1, k=1, log=lambda s: None)
core.revise = real_revise
assert "rev 1" in spec2["system_prompt"], spec2["system_prompt"]

task = json.load(open("tasks/bank_card_freeze.json"))
rules = [{"id": "r1", "rule": "verify first", "critical": True}, {"id": "r2", "rule": "give dates", "critical": False}]
sc = core.fallback_scenarios(task)[0]

def judge_with(reply):
    real, core.ask_json = core.ask_json, lambda *a, **kw: reply
    try:
        return core.judge(task, rules, sc, [("agent", "hi")])
    finally:
        core.ask_json = real

# the judge's "false" as a string is still a critical breach; a missing check is not a pass
assert abs(judge_with({"checks": {"r1": "false", "r2": True}, "goal_met": True})["score"] - 0.2 * 2 / 3) < 1e-9
j = judge_with({"checks": {"r1": True}, "goal_met": "yes"})
assert j["score"] == 2 / 3 and j["unchecked"] == ["r2"], j
assert judge_with([{"checks": {"[r1]": "pass", "r2": "pass"}, "goal_met": True}])["score"] == 1.0   # list-wrapped, bracketed ids

# wrapped lists and odd shapes from the model are unwrapped, not crashed on
assert core._as_list({"rules": [1, 2]}) == [1, 2] and core._as_list("x") == []
clean = core._clean({"name": "a", "system_prompt": "p", "first_message": "hi",
                     "tool_rules": [{"tool": "freeze_card", "when": "after verify"}], "guardrails": "never X"})
assert clean["tool_rules"] == ["freeze_card after verify"] and clean["guardrails"] == ["never X"], clean

# the caller never hears tool calls or results; the agent speaks after a result before the caller does
talk = core.simulate(spec, task, sc)
speakers = [s for s, _ in talk]
i = speakers.index("system")
assert speakers[i + 1] == "agent", talk
seen = []
real_ask = core.ask
def spy(role, prompt, system="", **kw):
    if role == "user":
        seen.append(prompt)
    return real_ask(role, prompt, system, **kw)
core.ask = spy
core.simulate(spec, task, sc)
core.ask = real_ask
assert seen and not any("CALL " in p or "RESULT" in p for p in seen), "caller heard tool traffic"

# one run that errors is left out, not scored 0; if nothing finishes the score is "not measured"
real_judge, n = core.judge, {"i": 0}
def sometimes(*a):
    n["i"] += 1
    if n["i"] % 2:
        raise ValueError("bad judge JSON")
    return real_judge(*a)
core.judge = sometimes
mean, per, failures, errors, evidence = core.evaluate(spec, task, report["rules"], core.fallback_scenarios(task) * 2, 2)
assert mean == 1.0 and len(errors) == 2, (mean, per, errors)
core.judge = lambda *a: (_ for _ in ()).throw(ValueError("down"))
assert core.evaluate(spec, task, report["rules"], core.fallback_scenarios(task), 2)[0] is None
core.judge = real_judge

# if every setup step fails, the builder still returns an agent and says it fell back
saved = core.extract_rules, core.scenarios, core.draft
def boom(*a, **kw):
    raise ConnectionError("simulated outage")
core.extract_rules = core.scenarios = core.draft = boom
spec3, report3 = core.build(task, rounds=2, n_train=2, n_val=1, k=1, log=lambda s: None)
core.extract_rules, core.scenarios, core.draft = saved
assert report3["fallbacks"] == {"rules": True, "customers": True, "draft": True}, report3["fallbacks"]
assert spec3["first_message"] and spec3["system_prompt"], spec3

# revise() is shown the worst failing calls themselves, not only the failure summaries
got = []
real_revise = core.revise
def spy_revise(spec_, task_, rules_, failures_, evidence_=()):
    got.append(evidence_)
    return real_revise(spec_, task_, rules_, failures_, evidence_)
core.revise = spy_revise
core.build(task, rounds=2, n_train=2, n_val=1, k=1, log=lambda s: None)
core.revise = real_revise
assert got and got[0] and "customer:" in got[0][0] and "(score 0.10)" in got[0][0], got

# rate limits are waited out (honouring Retry-After), and list-shaped content is read as text
import io  # noqa: E402
import urllib.error  # noqa: E402
from builder import llm  # noqa: E402
waits, tries = [], {"n": 0}
real_ask_, real_sleep, real_post = llm._ask, llm.SLEEP, llm._post
def limited(*a, **kw):
    tries["n"] += 1
    if tries["n"] <= 3:
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {"Retry-After": "30"} if tries["n"] == 1 else {}, io.BytesIO())
    return "ok"
llm._ask, llm.SLEEP = limited, waits.append
assert llm.ask("x", "y") == "ok" and waits[0] == 31 and len(waits) == 3, waits
llm._ask = real_ask_
os.environ.update(LLM_PROVIDER="openai", LLM_MODEL="m", LLM_BASE_URL="http://x", LLM_API_KEY="k")
llm._post = lambda *a: {"choices": [{"message": {"content": [{"type": "text", "text": "hel"}, {"type": "text", "text": "lo"}]}}]}
assert llm.ask("x", "y") == "hello"
llm._post = lambda *a: {"choices": [{"message": {"content": '{"a": 1'}, "finish_reason": "length"}]}
try:
    llm.ask("x", "y")
    raise AssertionError("a length-limited reply was accepted")
except llm.Truncated:
    pass
llm._post, llm.SLEEP = real_post, real_sleep
os.environ["LLM_PROVIDER"] = "stub"

# time budgets, on a fake clock: a dead provider cannot hold one call past CALL_BUDGET,
# and a build with --minutes stops early, still returns an agent, and clears its deadline
clock = {"t": 0.0}
real_now, real_sleep2 = llm.NOW, llm.SLEEP
llm.NOW = lambda: clock["t"]
llm.SLEEP = lambda s: clock.__setitem__("t", clock["t"] + s)
def hung(*a, **kw):
    clock["t"] += kw.get("timeout", 120)          # the request hangs until its timeout
    raise TimeoutError("hung")
llm._ask = hung
try:
    llm.ask("x", "y")
    raise AssertionError("a hung provider never gave up")
except (TimeoutError, llm.OutOfTime):
    pass
assert clock["t"] <= llm.CALL_BUDGET + 1, clock["t"]
llm._ask = real_ask_

def slow_stub(*a, **kw):
    clock["t"] += 1.0                             # every model call takes a second
    return real_ask_(*a, **kw)
llm._ask = slow_stub
logs = []
spec4, report4 = core.build(task, rounds=10, n_train=2, n_val=1, k=1, log=logs.append, minutes=3)
llm._ask, llm.NOW, llm.SLEEP = real_ask_, real_now, real_sleep2
assert report4["stopped_early"] and len(report4["pool"]) < 10, (report4["stopped_early"], len(report4["pool"]))
assert any(m.startswith("stopping after") for m in logs), logs            # the loop chose to stop...
assert not any("failed" in m for m in logs), [m for m in logs if "failed" in m]   # ...before a round ran out of time
assert report4["seconds"] <= 180, report4["seconds"]
assert spec4["system_prompt"] and llm.DEADLINE["at"] is None

# tools in the shapes platforms use are read with their exact arguments, and every agent
# is told those arguments plus the carry-ids-forward habit (the first real run failed on this)
schema_task = {"description": "d", "tools": [
    {"type": "function", "function": {"name": "freeze_card", "description": "freeze it", "parameters": {
        "type": "object", "properties": {"customer_id": {"type": "string"}, "card_last4": {"type": "string", "description": "last 4"},
                                         "reason": {"type": "string"}}, "required": ["customer_id", "card_last4"]}}},
    {"name": "lookup", "input_schema": {"properties": {"q": {"type": "string"}}, "required": ["q"]}},
    {"name": "old_style", "description": "args: {a, b}"}]}
tt = core.tools_text(schema_task)
assert "freeze_card(customer_id: string, card_last4: string (last 4), reason?: string)" in tt, tt
assert "lookup(q: string)" in tt and "old_style(): args: {a, b}" in tt, tt
prompt = core.agent_prompt(spec, schema_task)
assert "freeze_card(customer_id" in prompt and core.TOOL_HABITS[1] in prompt, prompt

# a simulated caller that refuses to play makes the run "not measured", never a 0
real_ask_core = core.ask
core.ask = lambda role, prompt, system="", **kw: ("I can't engage with this request. I'm not able to roleplay impersonation."
                                                  if role == "user" else real_ask_core(role, prompt, system, **kw))
mean_r, per_r, fails_r, errs_r, _ = core.evaluate(spec, task, report["rules"], core.fallback_scenarios(task), 2)
core.ask = real_ask_core
assert mean_r is None and per_r == [None] and len(errs_r) == 2 and "refused" in errs_r[0], (mean_r, per_r, errs_r)
assert not core._refused("I'm not comfortable giving my date of birth over the phone.")

# run_all: every task gets its own agent, id-less tasks never overwrite each other,
# and a broken task file is reported as missing instead of stopping the rest
import run_all  # noqa: E402
td = tempfile.mkdtemp()
for name, body in (("a.json", {"instructions": "Help callers activate a card.", "tools": []}),
                   ("b.json", {"instructions": "Help callers reset a PIN.", "tools": []})):
    with open(os.path.join(td, name), "w", encoding="utf-8") as fh:
        json.dump(body, fh)
with open(os.path.join(td, "broken.json"), "w", encoding="utf-8") as fh:
    fh.write("{not json")
summary = run_all.main([td, "--minutes", "1", "--rounds", "1", "--train", "1", "--val", "1", "--k", "1", "--out", os.path.join(td, "out")])
by_id = {v.get("task_id"): v["agent"] for v in summary.values()}
assert by_id.get("a") and by_id.get("b"), summary
assert not summary[os.path.join(td, "broken.json")]["agent"], summary

# --- second review's fixes ---
# a blocked model (logged out, usage limit) fails at once instead of retrying for minutes
import subprocess  # noqa: E402
waits.clear()
real_bounded = llm.run_bounded
llm.run_bounded = lambda *a: (json.dumps({"is_error": True, "result": "Failed to authenticate: OAuth session expired"}), "")
os.environ["LLM_PROVIDER"] = "claude-cli"
llm.SLEEP = waits.append
try:
    llm.ask("x", "y")
    raise AssertionError("blocked call returned")
except llm.Blocked:
    pass
llm.SLEEP, llm.run_bounded = real_sleep, real_bounded
os.environ["LLM_PROVIDER"] = "stub"
assert waits == [], waits

# tasks in other wordings are understood; unknown shapes fall back to the whole task
assert core.task_description({"instructions": "Help callers reset a PIN", "tools": []}) == "Help callers reset a PIN"
assert '"scenario": "x"' in core.task_description({"scenario": "x", "tools": [{"name": "t"}]})

# odd tool shapes do not crash
odd = core.tools_text({"tools": [{"function": "ping"}, {"name": "p", "parameters": {"properties": {"id": "string"}, "required": ["id"]}}, "bare"]})
assert "p(id: string)" in odd and "bare()" in odd, odd

# a long agent prompt goes to claude on stdin, never on the 32 KB command line
seen_cmd = {}
def fake_bounded(cmd, stdin_text, timeout):
    seen_cmd.update(cmd=cmd, input=stdin_text)
    return json.dumps({"result": "ok"}), ""
llm.run_bounded = fake_bounded
assert llm._claude_cli("hello", "S" * 40000, 30) == "ok"
llm.run_bounded = real_bounded
assert len(" ".join(seen_cmd["cmd"])) < 32000 and "S" * 40000 in seen_cmd["input"], len(" ".join(seen_cmd["cmd"]))

# a hung program whose child keeps the pipes open cannot hold a call past its timeout
# (real processes; with plain subprocess.run a 3 s timeout took 60 s here)
import sys  # noqa: E402
import time  # noqa: E402
t_start = time.time()
try:
    llm.run_bounded([sys.executable, "tests_fake_hang.py"], "x", 3)
    raise AssertionError("hung program returned")
except TimeoutError:
    pass
assert time.time() - t_start < 15, time.time() - t_start

# the simulated backend sees earlier calls with their results, in order
hist = core._tool_history([("agent", "One moment.\nCALL verify_identity {}"), ("system", "RESULT: verified, customer_id C1"),
                           ("customer", "ok"), ("agent", "CALL freeze_card {\"customer_id\": \"C1\"}")])
assert hist.splitlines() == ["CALL verify_identity {}", "  RESULT: verified, customer_id C1", 'CALL freeze_card {"customer_id": "C1"}'], hist

# a gateway answering 200 with HTML is a retryable connection error, not a crash
import urllib.request  # noqa: E402
real_urlopen = urllib.request.urlopen
class Html:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return b"<html>bad gateway</html>"
urllib.request.urlopen = lambda *a, **kw: Html()
try:
    llm._post("http://x", {}, {})
    raise AssertionError("HTML body accepted")
except ConnectionError:
    pass
urllib.request.urlopen = real_urlopen

# a reply cut off by the length limit is never parsed into a fragment of itself
from builder.llm import parse_json  # noqa: E402
assert parse_json('```json\n[{"a": 1}, {"b": 2}]\n```') == [{"a": 1}, {"b": 2}]
assert parse_json('```json\n[\n {"id": "r1", "critical": true},\n {"id": "r2", "crit') is None
assert parse_json('{"checks": {"r1": true}, "failures": ["did not proceed to') is None
assert parse_json('See rule [r1]. Here: {"x": 1}') == {"x": 1}

print("builder checks pass (%d model calls in the main run)" % report["model_calls"])
