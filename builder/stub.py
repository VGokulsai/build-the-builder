"""Canned model answers, so the loop can be tested with no key and no cost.

Each revision of the agent carries "rev N" in its instructions. The fake judge
scores rev 0 = 4, rev 1 = 8, rev 2 = 6: the second revision gets WORSE, so a
test can check that build() keeps the best spec rather than the latest.
"""
import json
import re

SCORES = {0: 4.0, 1: 8.0, 2: 6.0}


def _rev(text):
    m = re.search(r"rev (\d+)", text)
    return int(m.group(1)) if m else 0


def answer(role, prompt, system=""):
    if role == "draft":
        return json.dumps({"name": "stub agent", "system_prompt": "Help the customer. rev 0",
                           "first_message": "Hi, how can I help?", "tool_rules": ["verify before acting"],
                           "guardrails": ["never share card numbers"]})
    if role == "scenarios":
        n = int(re.search(r"Invent (\d+)", prompt).group(1))
        tag = "fresh" if "Do NOT repeat" in prompt else "first"
        return json.dumps([{"persona": "%s caller %d" % (tag, i), "goal": "freeze card",
                            "facts": {"card_last4": "1234"}, "success": "card frozen after verification"}
                           for i in range(n)])
    if role == "user":
        return "Thanks, that's all. [DONE]" if prompt.count("agent:") >= 2 else "I lost my card, please freeze it."
    if role == "agent":
        return "Freezing it now (rev %d).\nCALL freeze_card {\"card_last4\": \"1234\"}" % _rev(system)
    if role == "tool":
        return "RESULT: card frozen"
    if role == "judge":
        r = _rev(prompt)
        return json.dumps({"score": SCORES.get(r, 0.0), "failures": [] if r == 1 else ["skipped identity check (rev %d)" % r]})
    if role == "revise":
        start = prompt.index("Current agent (JSON):\n") + len("Current agent (JSON):\n")
        spec = json.loads(prompt[start:prompt.index("\n\nFailures")])
        spec["system_prompt"] = re.sub(r"rev \d+", "rev %d" % (_rev(spec["system_prompt"]) + 1), spec["system_prompt"])
        return json.dumps(spec)
    raise ValueError("stub has no answer for step %r" % role)
