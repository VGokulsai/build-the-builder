# Our builder: how to run it

One command: brief files in, a phone agent on Freya out.

```bash
source env.sh                                   # FREYA_API_KEY, FREYA_BANK_TEAM_KEY
pip install claude-agent-sdk                    # plus a Claude login or ANTHROPIC_API_KEY
python3 build.py <brief>.md --api <tool-api>.json
python3 build.py <base brief>.md <brief>.md --api <tool-api>.json   # a brief that builds on another
```

It saves and publishes the agent in a slot named after the last brief file, exports it to
`out/<slot>.workflow.json`, and writes the trace to `traces/<slot>-<time>.txt` (plain summary: start and
end time, every model call with its model and purpose, what was created on Freya, tests run) and
`traces/<slot>-<time>.jsonl` (every message). A run stops at 30 minutes; the saved agent is exported
whatever happens. Typical build time: 5 to 6 minutes.

## How it works

`build.py` runs Claude (Claude Agent SDK, `claude-opus-5-5` by default, `--model` to change) with one
skill, `.claude/skills/collections-builder/SKILL.md`. Claude:

1. reads the brief (a clean specification or raw bank material: mails, policy extracts, memos that
   override them, code lists) and the tool API file, and writes `out/<slot>/spec.md`;
2. writes `out/<slot>/agent.py` with `kitlib`, starting from the pattern in `agents/ref_ab.py`;
3. tests the workflow's own code locally (`out/<slot>/test_hooks.py`), lints it, and runs
   `kitlib/leftovers.py` so no rule of the public briefs survives in an agent for another brief;
4. saves and publishes it on Freya, and runs practice customers when the brief has them.

The design every agent gets:

- a code step computes all date facts from `now` and the brief's calendar (the model never computes dates);
- steps for opening, someone else answering, identity, the account, and the negotiation, routed on
  extracted enums and tool results, never on free text;
- guard hooks: a promise the brief does not allow (date, amount, one per product) never reaches the bank;
  the agent is told what to offer instead. `close_call`'s outcome and reason are derived in code from what
  was recorded, following the brief's outcome table;
- post-hooks give the model one plain instruction after every tool result.

`kitlib/`: `wf.py` (workflow building blocks generated from the tool API file, and `lint`), `datekit.py`
(business-day code that runs inside the workflow and in local tests), `chat.py`, `why.py` (call
timelines), `leftovers.py`. `briefs-test/` holds our generalisation tests: Brief A rewritten as raw bank
material, and Briefs C and D with changed rules, with practice expectations recomputed for them.

## Measured (practice customers, 3 runs each, customer counts only if all 3 pass)

- Reference agent: Brief A 10/10, Brief B 3/3.
- Built by the builder alone: Brief C (changed holidays, bands, deadlines, callback window) 10/10;
  Brief D (C plus up to three products) 3/3; Brief A as raw material 10/10 (1 run).
- Talking styles (Brief B): corrects, talkative, asks_back, in_words 3/3 each; pieces fixed on 11 Oct.
