"""One end-to-end check with the stub model: py -3 test_builder.py

The stub scores revision 1 highest and revision 2 lower, so the builder must keep
the best agent, not the last one, and must re-test it on customers it has not seen.
"""
import json
import os
import tempfile

os.environ["LLM_PROVIDER"] = "stub"

import run  # noqa: E402
from builder import core  # noqa: E402

out = tempfile.mkdtemp()
spec, report = run.main(["tasks/bank_card_freeze.json", "--rounds", "3", "--scenarios", "3", "--out", out])

scores = [h["score"] for h in report["history"]]
assert scores == [4.0, 8.0, 6.0], scores                     # the stub's rigged path happened
assert report["best_round"] == 1, report["best_round"]        # kept the best, not the latest
assert "rev 1" in spec["system_prompt"], spec["system_prompt"]
assert report["held_out"] == 8.0, report["held_out"]          # the winner was re-scored

first = core.scenarios({"description": "x"}, 3)
fresh = core.scenarios({"description": "x"}, 3, avoid=first)
assert not {s["persona"] for s in first} & {s["persona"] for s in fresh}, "fresh customers repeat old ones"

agent = json.load(open(os.path.join(out, "bank_card_freeze", "agent.json"), encoding="utf-8"))
assert agent["task_id"] == "bank_card_freeze" and set(core.SPEC_KEYS) <= set(agent), agent.keys()
print("builder checks pass (%d model calls)" % report["model_calls"])
