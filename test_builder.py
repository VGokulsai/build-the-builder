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
assert scores == [0.0, 1.0, 0.75, 0.75], scores            # critical breach scores 0; partial misses score in between
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
assert judge_with({"checks": {"r1": "false", "r2": True}, "goal_met": True})["score"] == 0.0
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
mean, per, failures, errors = core.evaluate(spec, task, report["rules"], core.fallback_scenarios(task) * 2, 2)
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

print("builder checks pass (%d model calls in the main run)" % report["model_calls"])
