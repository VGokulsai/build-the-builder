"""Canned model answers, so the loop can be tested with no key and no cost.

Each revision of the agent carries "rev N" in its instructions, and the fake
judge grades by revision against a 3-rule checklist (r1 critical):
  rev 0: breaks critical r1          -> score 0
  rev 1: passes everything           -> score 1.0
  rev 2+: misses non-critical r2     -> score 0.75
so a test can check the builder keeps the best agent, not the latest.
"""
import json
import re

RULES = [{"id": "r1", "rule": "verify identity before freezing", "critical": True},
         {"id": "r2", "rule": "say when the replacement arrives", "critical": False},
         {"id": "r3", "rule": "never read full card numbers", "critical": True}]


def _rev(text):
    m = re.search(r"rev (\d+)", text)
    return int(m.group(1)) if m else 0


def answer(role, prompt, system=""):
    if role == "rules":
        return json.dumps(RULES)
    if role == "draft":
        return json.dumps({"name": "stub agent", "system_prompt": "Help the caller. rev 0",
                           "first_message": "Hi, how can I help?", "tool_rules": ["verify before acting"],
                           "guardrails": ["never share card numbers"]})
    if role == "scenarios":
        n = int(re.search(r"Invent (\d+)", prompt).group(1))
        tag = "fresh" if "Do NOT repeat" in prompt else "first"
        return json.dumps([{"persona": "%s caller %d" % (tag, i), "goal": "freeze card", "facts": {"card_last4": "1234"},
                            "success": "card frozen after verification", "attacks": "r1" if i == 0 else ""}
                           for i in range(n)])
    if role == "user":
        return "Thanks, that's all. [DONE]" if prompt.count("agent:") >= 2 else "I lost my card, please freeze it."
    if role == "agent":
        return "One moment (rev %d).\nCALL freeze_card {\"card_last4\": \"1234\"}" % _rev(system)
    if role == "tool":
        return "RESULT: card frozen"
    if role == "judge":
        r = _rev(prompt)
        checks = {"r1": r != 0, "r2": r == 1, "r3": True}
        return json.dumps({"checks": checks, "goal_met": True,
                           "failures": [] if r == 1 else ["rev %d missed %s" % (r, [k for k, v in checks.items() if not v])]})
    if role == "revise":
        start = prompt.index("Current agent (JSON):\n") + len("Current agent (JSON):\n")
        spec = json.loads(prompt[start:prompt.index("\n\nFailures")])
        spec["system_prompt"] = re.sub(r"rev \d+", "rev %d" % (_rev(spec["system_prompt"]) + 1), spec["system_prompt"])
        return json.dumps(spec)
    raise ValueError("stub has no answer for step %r" % role)
