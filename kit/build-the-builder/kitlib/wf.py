"""Building blocks for Freya workflows. Generic: everything brief-specific is passed in.

Every rule here comes from docs/workflow-format.md and docs/tools-and-code.md, mostly from
the parts marked "verified in a working builder". The point is that a builder never has to
remember them: a tool built here always has its fields as body leaves with their own default,
its enums copied from the tool API file, a post-hook that tells the model what to do next,
and a workflow built here passes lint() before it is saved.
"""
import json
import re

# --------------------------------------------------------------------------- tool API


class ToolAPI:
    """The bank's tool API file (OpenAPI). Field names, enums and the server URL come from it,
    so a brief whose tools changed fields or allowed values still gets the right tools."""

    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            self.doc = json.load(f)
        self.base = self.doc["servers"][0]["url"].rstrip("/")
        self.ops = {}
        for p, methods in self.doc["paths"].items():
            for m, op in methods.items():
                name = op.get("operationId") or p.strip("/").split("/")[-1]
                schema = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                schema = self._resolve(schema)
                self.ops[name] = {"path": p, "method": m.upper(), "summary": op.get("summary") or op.get("description") or "",
                                  "props": {k: self._resolve(v) for k, v in schema.get("properties", {}).items()},
                                  "required": schema.get("required", [])}

    def _resolve(self, s):
        if isinstance(s, dict) and "$ref" in s:
            node = self.doc
            for part in s["$ref"].lstrip("#/").split("/"):
                node = node[part]
            return self._resolve(node)
        return s

    def names(self):
        return list(self.ops)

    def fields(self, tool):
        return self.ops[tool]["props"]

    def enum(self, tool, field):
        return list(self.ops[tool]["props"].get(field, {}).get("enum", []))

    def url(self, tool):
        return self.base + self.ops[tool]["path"]


# --------------------------------------------------------------------------- hooks

# Removes response headers (they only cost context) and adds `what_to_do_next`, the one line
# the agent model needs after a bare result (docs: "Tool results and the next turn").
# `rules` is Python source that sets `nxt` from `d` (the API body) and `vars`; it must not raise.
POST_HOOK = """try:
    import json
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if not isinstance(d, dict):
            d = {}
            result['data'] = d
        nxt = ''
%s
        if nxt:
            d['what_to_do_next'] = nxt
except Exception:
    pass
"""


def post_hook(rules):
    body = "\n".join("        " + line for line in rules.strip("\n").splitlines())
    return POST_HOOK % body


FAILED = ("if not d.get('ok'):\n"
          "    nxt = 'The bank did not carry this out (' + str(d.get('error') or 'service error') + '). Nothing was recorded. %s'")


def clean_code(src):
    """Code fields must not contain {{ or }} (docs: the field may be templated)."""
    if "{{" in src or "}}" in src:
        raise ValueError("code contains {{ or }}; read values from vars and avoid nested dict literals that end in }}")
    return src


# --------------------------------------------------------------------------- tools


def api_tool(api, name, *, description, model_fields=(), baked=None, enums=None, field_help=None,
             hook_rules=None, pre_code=None, retries=0, timeout_ms=12000, mapping=None):
    """A tool for a conversation node's `tools`. Fields in `baked` are fixed by the workflow
    (value may be a "{{var}}"); fields in `model_fields` are filled by the model. `enums`
    narrows a field to a subset of the API's allowed values for this node."""
    baked = dict(baked or {})
    enums, field_help = dict(enums or {}), dict(field_help or {})
    props, req = {}, []
    api_props = api.fields(name)
    for f, spec in api_props.items():
        if f in baked:
            props[f] = {"type": spec.get("type", "string"), "default": baked[f]}
        elif f in model_fields:
            leaf = {"type": spec.get("type", "string"), "default": "{{%s}}" % f}
            allowed = enums.get(f) or spec.get("enum")
            desc = field_help.get(f) or spec.get("description") or ""
            if allowed:
                leaf["enum"] = list(allowed)
                desc = (desc + " " if desc else "") + "One of: " + ", ".join(allowed) + "."
            if desc:
                leaf["description"] = desc
            props[f] = leaf
            if f in api.ops[name]["required"]:
                req.append(f)
    missing = [f for f in api.ops[name]["required"] if f not in props]
    if missing:
        raise ValueError("tool %s: required fields %s are neither baked nor model fields" % (name, missing))
    tool = {"type": "function", "config": {"timeoutMs": timeout_ms, "maxRetries": retries},
            "function": {"name": name, "handler": "__function__:api_call", "description": description,
                         "parameters": {"type": "object", "properties": {
                             "url": {"type": "string", "default": api.url(name)},
                             "method": {"type": "string", "default": api.ops[name]["method"]},
                             "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                             "body": {"type": "object", "properties": props, "required": req}}}}}
    if hook_rules:
        tool["post_process_code"] = clean_code(post_hook(hook_rules))
    if pre_code:
        tool["pre_process_code"] = clean_code("try:\n" + "\n".join("    " + l for l in pre_code.strip("\n").splitlines()) + "\nexcept Exception:\n    pass\n")
    if mapping:
        tool["response_mapping"] = [{"path": p, "variable": v} for p, v in mapping]
    return tool


def api_action(api, name, *, baked, hook_rules=None, pre_code=None, retries=0, timeout_ms=12000):
    """The same call for an api_request node's pre_actions: every field baked, nobody decides."""
    return api_tool(api, name, description=api.ops[name]["summary"], baked=baked, hook_rules=hook_rules,
                    pre_code=pre_code, retries=retries, timeout_ms=timeout_ms)


# --------------------------------------------------------------------------- transitions


def always(target, why="always"):
    return {"target_node": target, "description": why, "condition": {"operator": "always"}}


def when_any(target, why, *conds):
    """conds: (variable, operator, operand) or (variable, 'is_set'). OR of all."""
    out = []
    for c in conds:
        if len(c) == 2:
            out.append({"variable": c[0], "operator": c[1]})
        else:
            out.append({"variable": c[0], "operator": c[1], "operand": c[2]})
    return {"target_node": target, "description": why, "condition": {"logic": "or", "conditions": out}}


def when_all(target, why, *conds):
    inner = []
    for c in conds:
        inner.append({"variable": c[0], "operator": c[1]} if len(c) == 2 else {"variable": c[0], "operator": c[1], "operand": c[2]})
    return {"target_node": target, "description": why, "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": inner}]}}


def when_true(target, why, var):
    """A boolean from an API result arrives as "true" or "True"."""
    return when_any(target, why, (var, "equals", "true"), (var, "equals", "True"))


def when_tool(target, why):
    """The dialogue model moves on by calling transition_to_<target>."""
    return {"target_node": target, "description": why, "is_tool_call": True,
            "condition": {"operator": "matches_intent", "description": why}}


# --------------------------------------------------------------------------- nodes


def conversation(name, task, *, tools=(), transitions=(), on_enter=None, first_entry_only=True,
                 extraction=(), max_turns=40, routing_prompt=None):
    n = {"name": name, "node_type": "conversation", "task_message": task, "tools": list(tools),
         "transitions": list(transitions), "max_node_turns": max_turns,
         "on_enter": on_enter or {"type": "llm"}, "on_enter_first_entry_only": first_entry_only}
    if extraction:
        n["extraction_schema"] = list(extraction)
    if routing_prompt:
        n["routing_prompt"] = routing_prompt
    return n


def say(text):
    return {"type": "tts", "text": text}


def code_node(name, code, next_node, *, extra=()):
    return {"name": name, "node_type": "code", "passthrough": True, "passthrough_default_transition": next_node,
            "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                                                              "parameters": {"type": "object", "properties": {
                                                                  "code": {"type": "string", "default": clean_code(code)},
                                                                  "timeout_ms": {"type": "number", "default": 10000}}}}}],
            "transitions": list(extra) + [always(next_node)]}


def action_node(name, action, next_node, *, line=None, extra=(), mapping=()):
    """api_request passthrough node: runs one call on entry. `line` is spoken first (fixed)."""
    n = {"name": name, "node_type": "api_request", "passthrough": True, "passthrough_default_transition": next_node,
         "on_enter": say(line) if line else {"type": "silent"}, "disable_inactivity_monitor": True,
         "pre_actions": [action], "transitions": list(extra) + [always(next_node)]}
    if mapping:
        n["response_mapping"] = [{"path": p, "variable": v} for p, v in mapping]
    return n


def end_node(name, ended_reason):
    """Hangs up silently; the goodbye is said by the node before it."""
    return {"name": name, "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "transitions": [], "terminal": {"type": "function", "function": {
                "name": ended_reason, "handler": "__function__:end_call",
                "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}}


def extract(name, kind, description, *, enum=None, confidence=0.6):
    e = {"name": name, "type": kind, "description": description, "min_confidence": confidence}
    if enum:
        e["enum_values"] = list(enum)
    return e


# --------------------------------------------------------------------------- lint


def lint(wf, api=None):
    """Mechanical checks from the docs' checklists. Returns a list of problems (empty = fine)."""
    bad = []
    nodes = wf.get("nodes", {})
    if wf.get("initial_node") not in nodes:
        bad.append("initial_node %r is not a node" % wf.get("initial_node"))

    def walk_null(x, path):
        if x is None:
            bad.append("null value at " + path)
        elif isinstance(x, dict):
            for k, v in x.items():
                walk_null(v, path + "." + str(k))
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk_null(v, "%s[%d]" % (path, i))
    walk_null(wf, "workflow")
    if "agent_config" in wf:
        bad.append("agent_config must be left out")

    targets = set(nodes) | {"__previous__"}
    reach_end = {k for k, n in nodes.items() if n.get("node_type") == "end_call"}
    if not reach_end:
        bad.append("no end_call node")
    for key, n in nodes.items():
        t = n.get("node_type")
        if n.get("name") != key:
            bad.append("%s: name differs from key" % key)
        if t != "conversation" and n.get("tools"):
            bad.append("%s: tools on a %s node are dropped by the platform" % (key, t))
        if t == "conversation" and n.get("pre_actions"):
            bad.append("%s: pre_actions on a conversation node are dropped" % key)
        for tr in n.get("transitions", []):
            if tr.get("target_node") not in targets:
                bad.append("%s: transition to unknown node %r" % (key, tr.get("target_node")))
            c = tr.get("condition", {})
            if c.get("logic") == "and":
                bad.append("%s: top-level condition logic must be 'or'" % key)
            for leaf in _leaves(c):
                if leaf.get("operand") in ("true", "True", "false", "False"):
                    pair = {"true": "True", "True": "true", "false": "False", "False": "false"}[leaf["operand"]]
                    if not any(l.get("variable") == leaf.get("variable") and l.get("operand") == pair for l in _leaves(c)):
                        bad.append("%s: boolean %s tested only as %r" % (key, leaf.get("variable"), leaf["operand"]))
        if n.get("passthrough"):
            trs = n.get("transitions", [])
            if not trs or trs[-1].get("condition", {}).get("operator") != "always":
                bad.append("%s: passthrough node must end with an always transition" % key)
            if not n.get("passthrough_default_transition"):
                bad.append("%s: passthrough node without passthrough_default_transition" % key)
        if t == "end_call":
            if n.get("transitions"):
                bad.append("%s: end_call node with transitions" % key)
            if not n.get("terminal"):
                bad.append("%s: end_call node without terminal" % key)
        if t == "conversation" and not n.get("transitions"):
            bad.append("%s: conversation node with no way out" % key)
        if n.get("max_node_turns") and not n.get("max_turn_transition") and t == "conversation":
            pass  # allowed; the working builder does the same
        for tool in n.get("tools", []) + n.get("pre_actions", []):
            bad += _lint_tool(key, tool, api)
        for e in n.get("extraction_schema", []):
            if "min_confidence" not in e:
                bad.append("%s: extraction %s without min_confidence" % (key, e.get("name")))
    for tool in wf.get("tools", []):
        bad += _lint_tool("workflow", tool, api)
    # every node must be able to reach an end_call node
    graph = {k: {tr.get("target_node") for tr in n.get("transitions", [])} | ({n["passthrough_default_transition"]} if n.get("passthrough_default_transition") else set())
             for k, n in nodes.items()}
    for g in wf.get("global_nodes", {}).values():
        for tr in g.get("transitions", []):
            pass
    ok = set(reach_end)
    changed = True
    while changed:
        changed = False
        for k, outs in graph.items():
            if k not in ok and outs & ok:
                ok.add(k)
                changed = True
    for k in nodes:
        if k not in ok and nodes[k].get("node_type") != "end_call":
            bad.append("%s: no path to an end_call node" % k)
    return bad


def _leaves(c):
    if "conditions" in c:
        for x in c["conditions"]:
            yield from _leaves(x)
    elif "variable" in c:
        yield c


def _lint_tool(where, tool, api):
    bad = []
    f = tool.get("function", {})
    name = f.get("name")
    props = f.get("parameters", {}).get("properties", {})
    if f.get("handler") == "__function__:api_call":
        if "default" not in props.get("url", {}):
            bad.append("%s/%s: url has no default" % (where, name))
        body = props.get("body", {})
        if "default" in body and "properties" not in body:
            bad.append("%s/%s: body given as one default object; declare leaves" % (where, name))
        for fld, leaf in body.get("properties", {}).items():
            if "const" in leaf:
                bad.append("%s/%s: %s uses const (never sent); use default" % (where, name, fld))
            if "default" not in leaf:
                bad.append("%s/%s: body field %s has no default" % (where, name, fld))
        if api and name in api.ops:
            allowed = api.fields(name)
            for fld, leaf in body.get("properties", {}).items():
                if fld not in allowed:
                    bad.append("%s/%s: field %s is not in the tool API" % (where, name, fld))
                elif leaf.get("enum") and allowed[fld].get("enum") and not set(leaf["enum"]) <= set(allowed[fld]["enum"]):
                    bad.append("%s/%s: %s enum %s not allowed by the API %s" % (where, name, fld, leaf["enum"], allowed[fld]["enum"]))
            for fld in api.ops[name]["required"]:
                if fld not in body.get("properties", {}):
                    bad.append("%s/%s: required field %s missing" % (where, name, fld))
        elif api and name not in api.ops:
            bad.append("%s/%s: not a tool of the bank API" % (where, name))
    if f.get("handler") == "__function__:code_exec":
        code = props.get("code", {}).get("default", "")
        if "{{" in code or "}}" in code:
            bad.append("%s: code contains {{ or }}" % where)
        try:
            compile(code, where, "exec")
        except SyntaxError as e:
            bad.append("%s: code does not compile: %s" % (where, e))
    for hk in ("pre_process_code", "post_process_code"):
        if tool.get(hk):
            try:
                compile(tool[hk], where + "/" + hk, "exec")
            except SyntaxError as e:
                bad.append("%s/%s: %s does not compile: %s" % (where, name, hk, e))
    return bad
