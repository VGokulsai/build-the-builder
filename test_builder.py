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
print("builder checks pass (%d model calls in the main run)" % report["model_calls"])
