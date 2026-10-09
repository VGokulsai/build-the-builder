"""The builder: turn a task into an agent by drafting, testing, judging and revising.

An agent here is a plain dict ("spec"): instructions, tool rules, guardrails and
an opening line. platform.py turns that into whatever Freya's platform expects.

Tool calls inside simulated conversations are one line each:
    CALL tool_name {"arg": "value"}
and the simulated system answers with a line starting RESULT.
"""
import json

from builder.llm import ask, ask_json

SPEC_KEYS = ("name", "system_prompt", "first_message", "tool_rules", "guardrails")


def _task_text(task):
    tools = "\n".join("- %s: %s" % (t["name"], t.get("description", "")) for t in task.get("tools", []))
    return "TASK:\n%s\n\nTOOLS:\n%s" % (task["description"], tools or "(none)")


def draft(task):
    spec = ask_json("draft", """Design a customer-facing agent for this task.
%s

Return JSON with keys:
  name, system_prompt (complete instructions the agent follows, including the
  conversation flow and what to do when unsure), first_message (what it says
  first), tool_rules (list: when and how to use each tool; tool calls are written
  on their own line as: CALL tool_name {json args}), guardrails (list of things
  it must never do).""" % _task_text(task))
    return _clean(spec)


def scenarios(task, n, avoid=()):
    """n different simulated customers. `avoid` lists earlier ones so a fresh set really is new."""
    taken = ("\nDo NOT repeat these customers:\n" + "\n".join("- " + s["persona"] for s in avoid)) if avoid else ""
    found = ask_json("scenarios", """Invent %d different test customers for an agent doing this task.
%s
Mix easy, confused, impatient, off-topic and rule-breaking callers.%s

Return a JSON list; each item has: persona, goal, facts (what the customer knows,
e.g. account details), success (what a perfect agent achieves for them).""" % (n, _task_text(task), taken))
    return found[:n]


def _agent_system(spec):
    return "%s\n\nTool rules:\n%s\n\nNever:\n%s" % (
        spec["system_prompt"], "\n".join("- " + r for r in spec["tool_rules"]),
        "\n".join("- " + g for g in spec["guardrails"]))


def simulate(spec, task, sc, max_turns=6):
    """Play one conversation. Returns the transcript as a list of (speaker, text)."""
    talk = [("agent", spec["first_message"])]
    for _ in range(max_turns):
        so_far = "\n".join("%s: %s" % t for t in talk)
        user = ask("user", """You are a customer calling a company. Stay in character.
Persona: {persona}
Your goal: {goal}
Facts you know: {facts}

Conversation so far:
{so_far}

Write your next message only. If your goal is met or you give up, end with [DONE].""".format(so_far=so_far, **sc))
        talk.append(("customer", user))
        if "[DONE]" in user:
            break
        reply = ask("agent", "Conversation so far:\n%s\n\nWrite your next message." % "\n".join("%s: %s" % t for t in talk),
                    system=_agent_system(spec))
        talk.append(("agent", reply))
        for line in reply.splitlines():
            if line.strip().startswith("CALL "):
                result = ask("tool", """You simulate the company's system for this task.
%s
Customer facts: %s
The agent called: %s
Reply with one line starting RESULT: and a realistic result (an error if the call is wrong).""" % (
                    _task_text(task), json.dumps(sc["facts"]), line.strip()))
                talk.append(("system", result))
    return talk


def judge(task, sc, talk):
    """Score one conversation 0-10 and list what went wrong."""
    verdict = ask_json("judge", """Grade this agent conversation strictly.
%s

What success looks like for this customer: %s

Transcript:
%s

Return JSON: {"score": 0-10, "failures": [short, specific problems; empty if none]}""" % (
        _task_text(task), sc["success"], "\n".join("%s: %s" % t for t in talk)))
    return {"score": float(verdict.get("score", 0)), "failures": list(verdict.get("failures", []))}


def evaluate(spec, task, scs):
    results = [judge(task, sc, simulate(spec, task, sc)) for sc in scs]
    return sum(r["score"] for r in results) / max(1, len(results)), results


def revise(spec, task, failures):
    new = ask_json("revise", """Improve this agent so these failures stop happening, without breaking what works.
%s

Current agent (JSON):
%s

Failures seen in testing:
%s

Return the full improved agent as JSON with the same keys.""" % (
        _task_text(task), json.dumps(spec, indent=1), "\n".join("- " + f for f in failures)))
    return _clean(new)


def build(task, rounds=3, n_scenarios=4, log=print):
    """Draft, then test-and-revise for `rounds`, keeping the best spec seen.
    Finally re-test the winner on fresh customers, so the reported score was not fitted to its tests."""
    tests = scenarios(task, n_scenarios)
    spec, best, history = draft(task), None, []
    for r in range(rounds):
        score, results = evaluate(spec, task, tests)
        failures = [f for res in results for f in res["failures"]]
        history.append({"round": r, "score": score, "failures": failures, "spec": spec})
        log("round %d: score %.1f, %d failures" % (r, score, len(failures)))
        if best is None or score > best["score"]:
            best = history[-1]
        if r < rounds - 1:
            spec = revise(best["spec"], task, best["failures"] or ["none seen; make it more robust"])
    fresh = scenarios(task, n_scenarios, avoid=tests)
    held_out, _ = evaluate(best["spec"], task, fresh)
    log("best was round %d (%.1f); on fresh customers it scores %.1f" % (best["round"], best["score"], held_out))
    return best["spec"], {"history": history, "best_round": best["round"], "held_out": held_out}


def _clean(spec):
    missing = [k for k in SPEC_KEYS if k not in spec]
    if missing:
        raise ValueError("agent spec is missing %s" % missing)
    for k in ("tool_rules", "guardrails"):
        if isinstance(spec[k], str):
            spec[k] = [spec[k]]
    return {k: spec[k] for k in SPEC_KEYS}
