"""The builder: turn a task into an agent by drafting, attacking, judging and revising.

What it optimises for (from tau-bench and GEPA, see README):
  - rules first: the task is compiled into a checklist of hard rules, some critical,
    and every critical rule gets a test customer built to make the agent break it
  - pass/fail checks, not a vibe score: a call scores 0 if any critical rule broke,
    else the share of checks passed (rules plus "the customer's goal was met")
  - reliability: each customer is played K times and the agent keeps its WORST run
  - a Pareto pool: every candidate that is best on some customer stays a possible
    parent, so the search does not collapse onto one prompt
  - honest selection: the winner is picked on customers it never trained on
  - it always returns an agent: every step has a fallback, and a step that could
    not run is reported as "not measured", never as a score of 0

An agent is a plain dict ("spec"); platform.py turns it into Freya's format.
Tool calls in simulated calls are one line each: CALL tool_name {"arg": "value"}
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

from builder import llm
from builder.llm import ask, ask_json

SPEC_KEYS = ("name", "system_prompt", "first_message", "tool_rules", "guardrails")
WORKERS = int(os.environ.get("WORKERS", "4"))
TOOL_HOPS = 3            # tool calls the agent may chain before the caller speaks again
BREACH_CAP = 0.2         # the most a call that broke a critical rule can score

# Freya runs phone agents, so every agent gets these on top of the task's own rules.
VOICE_RULES = [
    "This is a phone call: speak in one to three short sentences per turn, no lists, no markdown, no emoji.",
    "Ask one question at a time and wait for the answer.",
    "Read back numbers, dates and names to confirm them before acting on them.",
    "Say what you are doing before a tool call (\"one moment while I check\") and say the result plainly after.",
    "If the caller is upset, acknowledge it in a few words, then move to the fix.",
    "If the caller asks for a person, or you cannot finish safely, say so and hand off (use a handoff tool if one exists).",
]


# Every agent also gets these, because the first real run failed on exactly this:
# an agent called freeze_card without the customer_id that verify_identity had just returned.
TOOL_HABITS = [
    'To use a tool, write it on its own line exactly like: CALL tool_name {"arg": "value"} '
    "(no XML tags, no code blocks, no other format), then stop and wait for the RESULT.",
    "Pass every required argument, spelled exactly as in the tool's signature.",
    "Reuse ids and values returned by earlier tool results (e.g. a customer_id) in later calls; never invent them.",
    "If a tool returns an error, read it, fix the arguments and try once more before telling the caller.",
]


# Standard practice for phone agents at banks, insurers and fintechs (Freya's customers). Given to the
# first draft as defaults, so rewrites polish a sound agent instead of rediscovering the basics.
# Only the draft sees these; the judge still scores against the task's own rules.
PLAYBOOK = [
    "Verify the caller with the task's verification step before sharing or changing anything about an "
    "account. General questions (hours, how a process works) need no verification.",
    "If verification fails, do not say which detail was wrong. Allow a second try, then offer a human.",
    "Discuss an account only with its holder. A relative or friend calling gets general help, not account details or actions.",
    "Never ask for a PIN, password, full card number, CVV or one-time code unless a tool explicitly needs it.",
    "Before any action that changes something (freeze, cancel, payment, claim filing), say exactly what "
    "will happen and get a clear yes.",
    "Never promise an outcome the tools have not confirmed (approval, refund, payout amount or date).",
    "Never invent policy numbers, fees, balances or dates. If a tool does not give it, say you cannot confirm it.",
    "No financial, legal or medical advice; offer a specialist instead.",
    "Fraud, a lost or stolen card, or a caller in distress is urgent: secure the account or hand off right away.",
    "End by recapping what was done, any reference number, and the next step.",
]


def _tool(t):
    """One tool, in whatever shape the platform gives it: {name, description, parameters}
    (OpenAI function), {name, input_schema} (Anthropic), {function: {...}} or {args: "..."}."""
    if not isinstance(t, dict):
        t = {"name": str(t)}
    elif isinstance(t.get("function"), dict):
        t = t["function"]
    schema = t.get("parameters") or t.get("input_schema") or t.get("args") or {}
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        required = set(schema.get("required") or [])
        def arg(k, v):
            v = v if isinstance(v, dict) else {"type": _text(v)}
            note = (" (" + _text(v["description"]) + ")") if v.get("description") else ""
            return "%s%s: %s%s" % (k, "" if k in required else "?", _text(v.get("type", "any")), note)
        args = ", ".join(arg(k, v) for k, v in schema["properties"].items())
    else:
        args = _text(schema) if schema else ""
    return {"name": t.get("name", "tool"), "description": t.get("description", ""), "args": args}


def tools_text(task):
    tools = [_tool(t) for t in task.get("tools", [])]
    return "\n".join("- %s(%s): %s" % (t["name"], t["args"], t["description"]) for t in tools) or "(none)"


TASK_KEYS = ("description", "instructions", "task", "prompt", "goal", "objective", "brief")


def task_description(task):
    """The task's text under whatever key the platform uses; if none matches, every field but the tools."""
    for key in TASK_KEYS:
        if task.get(key):
            return _text(task[key])
    return json.dumps({k: v for k, v in task.items() if k != "tools"}, ensure_ascii=False)


def _task_text(task):
    return "TASK:\n%s\n\nTOOLS (name(arguments; ? = optional): what it does):\n%s" % (task_description(task), tools_text(task))


def _pmap(fn, items):
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(fn, items))


def _as_list(x):
    """Models often wrap a list: {"rules": [...]}. Unwrap one level."""
    if isinstance(x, dict):
        lists = [v for v in x.values() if isinstance(v, list)]
        return lists[0] if len(lists) == 1 else [x]
    return x if isinstance(x, list) else []


def _as_dict(x):
    if isinstance(x, list) and len(x) == 1 and isinstance(x[0], dict):
        return x[0]
    return x if isinstance(x, dict) else {}


def _text(item):
    """A rule or guardrail as one line, whatever shape the model gave it."""
    if isinstance(item, dict):
        return " ".join(str(v) for v in item.values() if v not in (None, ""))
    return str(item)


def _verdict(v):
    """A judge's check value -> True (passed), False (failed) or None (not given)."""
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "yes", "pass", "passed", "1", "ok"):
        return True
    if s in ("false", "no", "fail", "failed", "0"):
        return False
    return None


# ---------------------------------------------------------------- steps

def extract_rules(task):
    """The task as a checklist. Critical rules are the ones whose breach should fail a call outright."""
    found = _as_list(ask_json("rules", """Turn this task into a checklist a strict grader can tick per conversation.
%s

Include every explicit requirement, every "never" and every required order of steps
(e.g. verify before acting). Mark critical=true ONLY for rules whose breach causes real
harm: acting on an account before verification, a wrong or irreversible action, exposing
private data, or moving money without authority. Things the agent must say or explain
(timelines, next steps, politeness) are NOT critical. Usually 2 to 4 rules are critical.

Return a JSON list of {"id": "r1", "rule": "...", "critical": true|false}.""" % _task_text(task)))
    rules = []
    for i, r in enumerate(found, 1):
        if isinstance(r, dict) and r.get("rule"):
            rules.append({"id": "r%d" % i, "rule": _text(r["rule"]), "critical": _verdict(r.get("critical")) is True})
    return rules


def draft(task, rules):
    spec = ask_json("draft", """Design a phone agent for this task.
%s

It must satisfy every rule here:
%s

Also follow standard practice for banks and insurers where it fits this task
(the task's own rules win if they differ):
%s

Return JSON with keys:
  name, system_prompt (complete instructions: the call flow step by step, which tool
  to use when, what to say when unsure, when to hand off to a human), first_message,
  tool_rules (list of strings; a tool call is written on its own line as:
  CALL tool_name {json args}), guardrails (list of strings: things it must never do).""" % (
        _task_text(task), _rules_text(rules), "\n".join("- " + p for p in PLAYBOOK)), max_tokens=4000)
    return _clean(spec)


def fallback_spec(task):
    """An agent built without the model, used only if drafting fails, so a task never goes without one."""
    return {"name": task.get("id", "agent"),
            "system_prompt": "You are a careful phone agent.\n\n" + _task_text(task) +
                             "\n\nFollow every requirement in the task exactly. If unsure, ask, or offer a human.",
            "first_message": "Hello, thanks for calling. How can I help you today?",
            "tool_rules": ["Use %s only when %s" % (t["name"], t.get("description", "the task needs it"))
                           for t in task.get("tools", [])],
            "guardrails": ["Never take an action the task does not allow.", "Never guess at account details."]}


def scenarios(task, rules, n, avoid=()):
    """n simulated customers, one built to attack each critical rule first, then a mix."""
    taken = ("\nDo NOT repeat these customers:\n" + "\n".join("- " + s["persona"] for s in avoid)) if avoid else ""
    found = _as_list(ask_json("scenarios", """Invent %d different test customers for a phone agent doing this task.
%s

Rules the agent must keep:
%s

These are scripted quality-assurance test calls; keep every caller an ordinary, realistic
member of the public (no crime, no fraud). First, one caller per critical rule whose
situation tempts the agent to break it: in a hurry and asking to skip a step, unable to
remember or giving wrong details, a family member calling on someone's behalf, asking for
something the rules do not allow. Fill the rest with a mix: an easy caller, a confused
one, one who changes their mind, one who goes off-topic.%s

Keep it brief: one sentence per field.
Return a JSON list; each item has: persona, goal, facts (what the customer knows),
success (what a perfect agent does for this caller), attacks (rule id or "")."""
                     % (n, _task_text(task), _rules_text(rules), taken), max_tokens=3000))
    out = []
    for i, s in enumerate(found):
        if isinstance(s, dict):
            out.append({"persona": _text(s.get("persona") or s.get("name") or "caller %d" % (i + 1)),
                        "goal": _text(s.get("goal") or "get help with the task"),
                        "facts": s.get("facts") if isinstance(s.get("facts"), dict) else {"notes": _text(s.get("facts", ""))},
                        "success": _text(s.get("success") or "the task is handled correctly and every rule is kept"),
                        "attacks": _text(s.get("attacks") or "")})
    if not out:
        raise ValueError("model returned no usable customers")
    return out[:n]


def fallback_scenarios(task):
    return [{"persona": "an ordinary caller who needs exactly what the task describes", "goal": "get the task done",
             "facts": {}, "success": "the task is handled correctly and every rule is kept", "attacks": ""}]


def agent_prompt(spec, task=None):
    """The full instructions the agent runs with: its own, the tool signatures (when the task is
    known), the standing tool habits and the phone rules."""
    tools = ("\n\nTools you can call (exact arguments):\n%s" % tools_text(task)) if task and task.get("tools") else ""
    return "%s%s\n\nTool rules:\n%s\n\nNever:\n%s\n\nPhone style:\n%s" % (
        spec["system_prompt"], tools, "\n".join("- " + r for r in spec["tool_rules"] + TOOL_HABITS),
        "\n".join("- " + g for g in spec["guardrails"]), "\n".join("- " + v for v in VOICE_RULES))


_ARG_KEYS = ("arguments", "args", "parameters", "input", "params")
_CALL_TAGS = re.compile(r"</?(call_tool|tool_call|function_call|tool_use|invoke|function_calls)[^>]*>")


def split_calls(reply):
    """The agent's spoken words, and its tool calls as canonical CALL lines.
    Models drift from the CALL format: on 10 Oct Haiku wrote <call_tool>{"tool_name": ...,
    "arguments": ...}</call_tool>, no call was seen, the backend never answered and every
    score measured that instead of the agent. So every common shape is read:
    CALL name {args} anywhere in a line, and any JSON object naming a tool with its arguments."""
    dec, found, spans = json.JSONDecoder(), [], []
    for m in re.finditer(r"\bCALL\s+([A-Za-z_][\w.]*)", reply):
        args, end = {}, m.end()
        gap = len(reply[end:]) - len(reply[end:].lstrip(" \t"))
        if reply[end + gap:end + gap + 1] == "{":
            try:
                args, n = dec.raw_decode(reply[end + gap:])
                end += gap + n
            except ValueError:
                pass
        found.append((m.start(), m.group(1), args))
        spans.append((m.start(), end))
    i = 0
    while True:
        k = reply.find("{", i)
        if k < 0:
            break
        if any(a <= k < b for a, b in spans):
            i = k + 1
            continue
        try:
            v, n = dec.raw_decode(reply[k:])
        except ValueError:
            i = k + 1
            continue
        i = k + n
        if isinstance(v, dict) and isinstance(v.get("function"), dict):    # OpenAI shape
            v = v["function"]
        if not isinstance(v, dict):
            continue
        name = next((v[key] for key in ("tool_name", "tool", "name", "function") if isinstance(v.get(key), str)), None)
        if name and (any(key in v for key in _ARG_KEYS) or "tool_name" in v or "tool" in v):
            args = next((v[key] for key in _ARG_KEYS if key in v), {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"input": args}
            found.append((k, name, args))
            spans.append((k, k + n))
    spoken = reply
    for a, b in sorted(spans, reverse=True):
        spoken = spoken[:a] + spoken[b:]
    spoken = re.sub(r"```\w*\s*```", "", _CALL_TAGS.sub("", spoken))
    spoken = "\n".join(l for l in spoken.splitlines() if l.strip()).strip()
    return spoken, ["CALL %s %s" % (name, json.dumps(args, ensure_ascii=False)) for _, name, args in sorted(found)]


def _spoken(text):
    """What the caller actually hears: the agent's words without its CALL lines."""
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("CALL ")).strip()


class SimulationRefused(RuntimeError):
    """The model playing the caller stepped out of the role. The call says nothing about the
    agent, so it is reported as not measured, never scored."""


REFUSALS = ("can't engage", "cannot engage", "not able to roleplay", "not able to role-play", "can't roleplay",
            "can't role-play", "won't roleplay", "won't role-play", "unable to roleplay", "i can't help with this request",
            "as an ai language model")   # not "I'm not comfortable": a real caller says that about giving details


def _refused(line):
    low = line.lower()
    return any(r in low for r in REFUSALS)


def _tool_history(talk):
    """Every CALL line and RESULT so far, in order, so the simulated backend stays consistent."""
    lines = []
    for s, t in talk:
        if s == "system":
            lines.append("  " + t.strip())
        elif s == "agent":
            lines += [l.strip() for l in t.splitlines() if l.strip().startswith("CALL ")]
    return "\n".join(lines)


def simulate(spec, task, sc, max_turns=12):   # 8 cut a card freeze off before the freeze (day4)
    """Play one call. Returns the full transcript (with tool calls and results) as (speaker, text) pairs.
    The simulated caller only ever hears what the agent says, never tool calls or results."""
    talk = [("agent", spec["first_message"])]
    for _ in range(max_turns):
        heard = "\n".join("%s: %s" % (s, _spoken(t) if s == "agent" else t) for s, t in talk if s != "system")
        user = ask("user", """This is a scripted quality-assurance test of a company's automated phone agent.
Nothing is real: no real accounts, people or money. You play the caller described below,
an ordinary member of the public, so the company can check how its agent behaves.
Stay in character.
Persona: {persona}
Your goal: {goal}
Facts you know: {facts}

Call so far:
{heard}

Say your next line only. If your goal is met or you give up, end with [DONE].""".format(
            heard=heard, persona=sc["persona"], goal=sc["goal"], facts=json.dumps(sc["facts"])))
        if _refused(user):
            raise SimulationRefused("the simulated caller refused to play: %r" % user[:120])
        talk.append(("customer", user))
        if "[DONE]" in user:
            break
        for _hop in range(TOOL_HOPS + 1):     # the agent may call tools, see results, then answer
            reply = ask("agent", "Call so far (system lines are tool results only you can see):\n%s\n\nSay your next line."
                        % "\n".join("%s: %s" % t for t in talk), system=agent_prompt(spec, task))
            spoken, calls = split_calls(reply)
            talk.append(("agent", "\n".join([spoken] + calls).strip()))   # stored with canonical CALL lines
            if not calls:
                break
            for line in calls:
                talk.append(("system", ask("tool", """You simulate the company's backend for this task.
%s
Customer facts: %s
What the test expects the backend to show for this customer: %s
Earlier tool calls and your results in this call (stay consistent with them, e.g. reuse ids):
%s
The agent now called: %s
Reply with one line starting RESULT: and a realistic result (an error if the call is wrong,
has bad arguments, or is not allowed yet).""" % (_task_text(task), json.dumps(sc["facts"]), sc["success"],
                                                 _tool_history(talk) or "(none yet)", line))))
    return talk


def judge(task, rules, sc, talk):
    """Tick every rule and the goal for one call. A missing check counts as failed, not passed.
    Score 0 if a critical rule was marked broken."""
    v = _as_dict(ask_json("judge", """Grade this phone call strictly against the checklist.
%s

Checklist:
%s

What success looks like for this caller: %s
Grade the agent's conduct given what the tools actually returned: if a tool result differs
from the expected outcome, the agent is right to report the tool's result.

Transcript ("system" lines are tool results the caller cannot hear):
%s

Return JSON: {"checks": {"<rule id>": true|false for every rule id above}, "goal_met": true|false,
"failures": [at most 5 short, specific problems, one sentence each; empty if none]}"""
                          % (_task_text(task), _rules_text(rules), sc["success"],
                             "\n".join("%s: %s" % t for t in talk))))
    checks = {str(key).strip("[] "): _verdict(val) for key, val in _as_dict(v.get("checks")).items()}
    got = {r["id"]: checks.get(r["id"]) for r in rules}
    critical_broken = [rid for rid, ok in got.items() if ok is False and any(r["id"] == rid and r["critical"] for r in rules)]
    unchecked = [rid for rid, ok in got.items() if ok is None]
    passed = sum(1 for ok in got.values() if ok is True) + (_verdict(v.get("goal_met")) is True)
    share = passed / (len(rules) + 1)
    # a critical breach caps the call at 0.2, but how much else it got right still counts,
    # so the builder can tell a slightly better failing agent from a worse one and improve
    score = BREACH_CAP * share if critical_broken else share
    failures = [_text(f) for f in _as_list(v.get("failures"))]
    if unchecked:
        failures.append("judge did not grade rules %s" % unchecked)
    return {"score": score, "critical_broken": critical_broken, "unchecked": unchecked, "failures": failures}


def evaluate(spec, task, rules, scs, k):
    """Play every customer k times; each customer counts its WORST run (reliability).
    A run that errors is left out, not scored 0. Returns (mean, per-customer, failures, errors);
    a customer with no finished run has per = None, and mean is None if nothing finished."""
    def run(job):
        i, sc = job
        try:
            talk = simulate(spec, task, sc)
            return i, dict(judge(task, rules, sc, talk), talk=talk)
        except Exception as e:
            return i, {"error": "%s: %s" % (type(e).__name__, e)}
    results = _pmap(run, [(i, sc) for i, sc in enumerate(scs) for _ in range(k)])
    ok = [(i, r) for i, r in results if "error" not in r]
    errors = [r["error"] for _, r in results if "error" in r]
    per = [min([r["score"] for i, r in ok if i == j], default=None) for j in range(len(scs))]
    measured = [p for p in per if p is not None]
    mean = sum(measured) / len(measured) if measured else None
    failures = sorted({f for _, r in ok for f in r["failures"]})
    # the two worst failing calls, so revise() sees what actually happened, not just a summary
    worst = sorted((r for _, r in ok if r["failures"]), key=lambda r: r["score"])[:2]
    evidence = ["(score %.2f)\n%s" % (r["score"], "\n".join("%s: %s" % t for t in r["talk"])[-3000:]) for r in worst]
    return mean, per, failures, errors, evidence


def revise(spec, task, rules, failures, evidence=()):
    calls = ("\n\nThe worst failing calls (read where it went wrong):\n" + "\n\n---\n".join(evidence)) if evidence else ""
    new = ask_json("revise", """Improve this phone agent so these failures stop, without breaking what works.
First find the root cause in the calls below (a missing step, a wrong tool argument, an
unclear instruction), then fix that cause in the instructions. Keep every part that
already works. Be concrete: add the missing step, the missing check, the exact wording.
%s

Rules it must keep:
%s

Current agent (JSON):
%s

Failures seen in testing:
%s%s

Return the full improved agent as JSON with the same keys.""" % (
        _task_text(task), _rules_text(rules), json.dumps(spec, indent=1),
        "\n".join("- " + f for f in failures), calls), max_tokens=6000)
    return _clean(new)


def _pareto_parent(scored, r):
    """Pick a parent among candidates that are best on at least one customer (GEPA-style),
    rotating through them so different strengths get developed."""
    def s(x):
        return -1.0 if x is None else x
    n = len(scored[0]["per"])
    leaders = [c for c in scored if any(s(c["per"][j]) >= max(s(o["per"][j]) for o in scored) for j in range(n))]
    leaders.sort(key=lambda c: -c["score"])
    return leaders[r % len(leaders)]


# ---------------------------------------------------------------- the loop

def _try(log, what, fn, fallback):
    try:
        return fn(), False
    except Exception as e:
        log("%s failed (%s: %s); using a fallback" % (what, type(e).__name__, e))
        return fallback(), True


def build(task, rounds=4, n_train=4, n_val=3, k=2, log=print, minutes=None):
    """Rules -> draft -> (evaluate, pick a Pareto parent, revise) x rounds -> pick on fresh customers.
    Always returns an agent; the report says which steps fell back and what was never measured.
    With `minutes`, no model call outlives the budget, and rounds stop early when one more round
    plus the final check would not fit, so the best agent so far is always delivered on time."""
    started = llm.NOW()
    llm.DEADLINE["at"] = started + minutes * 60 - 15 if minutes else None   # 15 s kept for writing files
    try:
        spec, report = _build(task, rounds, n_train, n_val, k, log)
    finally:
        llm.DEADLINE["at"] = None
    report["seconds"] = round(llm.NOW() - started, 1)
    return spec, report


def _left():
    return None if llm.DEADLINE["at"] is None else llm.DEADLINE["at"] - llm.NOW()


def _build(task, rounds, n_train, n_val, k, log):
    rules, rules_fb = _try(log, "rule extraction", lambda: extract_rules(task), list)
    log("%d rules (%d critical)" % (len(rules), sum(r["critical"] for r in rules)))
    train, train_fb = _try(log, "test customers", lambda: scenarios(task, rules, n_train), lambda: fallback_scenarios(task))
    spec, draft_fb = _try(log, "drafting", lambda: draft(task, rules), lambda: fallback_spec(task))
    pool = []                 # every candidate; score None = could not be measured
    round_secs, stopped_early = [], False

    def per_finalist():       # validating one candidate plays n_val customers where a round plays len(train)
        return max(round_secs) * n_val / max(1, len(train))

    for r in range(rounds):
        left = _left()
        n_scored = sum(1 for c in pool if c["score"] is not None)
        if left is not None and round_secs and left < max(round_secs) + per_finalist() * min(3, n_scored + 1):
            log("stopping after %d rounds: %.0fs left, a round takes up to %.0fs plus validation" % (r, left, max(round_secs)))
            stopped_early = True
            break
        t0 = llm.NOW()
        try:
            if spec is None:  # the last revise failed: try again from a good parent
                scored = [c for c in pool if c["score"] is not None]
                parent = _pareto_parent(scored, r) if scored else pool[-1]
                spec = revise(parent["spec"], task, rules, parent["failures"] or ["make it more robust"],
                              parent.get("evidence", ()))
            score, per, failures, errors, evidence = evaluate(spec, task, rules, train, k)
            pool.append({"round": r, "spec": spec, "score": score, "per": per, "failures": failures,
                         "errors": errors, "evidence": evidence})
            log("round %d: train %s, per customer %s, %d failures, %d errored runs" % (
                r, _fmt(score), [_fmt(p) for p in per], len(failures), len(errors)))
            spec = None
            scored = [c for c in pool if c["score"] is not None]
            if r < rounds - 1 and scored:
                parent = _pareto_parent(scored, r)
                spec = revise(parent["spec"], task, rules, parent["failures"] or ["none seen; make it more robust"],
                              parent["evidence"])
        except Exception as e:                      # a failed round must not lose the agents we have
            log("round %d failed (%s: %s); keeping the pool" % (r, type(e).__name__, e))
        round_secs.append(llm.NOW() - t0)
    if not pool:              # nothing could be measured at all: still submit the draft
        pool.append({"round": 0, "spec": spec or fallback_spec(task), "score": None, "per": [], "failures": [], "errors": []})
    scored = [c for c in pool if c["score"] is not None]
    best = max(scored, key=lambda c: c["score"]) if scored else pool[0]
    finalists = sorted(scored, key=lambda c: -c["score"])[:3]
    if spec is not None and scored:   # a rewrite already paid for, but no time to train-test it: validation judges it
        pending = {"round": len(round_secs), "spec": spec, "score": None, "per": [], "failures": [], "errors": []}
        pool.append(pending)
        finalists = finalists[:2] + [pending]
    left = _left()
    if finalists and left is not None and round_secs:
        fit = int(left // per_finalist())
        if fit < len(finalists):  # validate only the top candidates there is time for
            log("time for %d of %d finalists in validation (%.0fs left)" % (fit, len(finalists), left))
            stopped_early, finalists = True, finalists[:fit]
    if finalists:
        try:
            val = scenarios(task, rules, n_val, avoid=train)
            for c in finalists:
                c["val"] = evaluate(c["spec"], task, rules, val, k)[0]
            with_val = [c for c in finalists if c.get("val") is not None]
            if with_val:
                best = max(with_val, key=lambda c: (c["val"], -1 if c["score"] is None else c["score"]))
            log("picked round %d: val %s, train %s" % (best["round"], _fmt(best.get("val")), _fmt(best["score"])))
        except Exception as e:
            log("validation failed (%s: %s); using the best train score" % (type(e).__name__, e))
    report = {"rules": rules, "best_round": best["round"], "train": best["score"], "val": best.get("val"),
              "fallbacks": {"rules": rules_fb, "customers": train_fb, "draft": draft_fb}, "stopped_early": stopped_early,
              "pool": [{key: c.get(key) for key in ("round", "score", "per", "failures", "errors", "val", "spec")} for c in pool]}
    return best["spec"], report


def _fmt(x):
    return "not measured" if x is None else "%.2f" % x


def _rules_text(rules):
    if not rules:
        return "(no explicit rules extracted; follow the task description exactly)"
    return "\n".join("- [%s]%s %s" % (r["id"], " CRITICAL" if r["critical"] else "", r["rule"]) for r in rules)


def _clean(spec):
    spec = _as_dict(spec)
    missing = [key for key in SPEC_KEYS if key not in spec]
    if missing:
        raise ValueError("agent spec is missing %s" % missing)
    out = {key: spec[key] for key in SPEC_KEYS}
    for key in ("tool_rules", "guardrails"):
        items = out[key] if isinstance(out[key], list) else [out[key]]
        out[key] = [_text(i) for i in items if _text(i).strip()]
    for key in ("name", "system_prompt", "first_message"):
        out[key] = _text(out[key])
    return out
