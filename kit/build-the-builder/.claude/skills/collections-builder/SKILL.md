---
name: collections-builder
description: Build a Freya phone agent for a bank collections brief (clean specification or raw bank material) with kitlib, test it, save and publish it, and export it. Use when asked to build a phone agent from a brief.
---

# Build a collections phone agent from a brief

You are the builder. You get brief files, a tool API file and a slot name. You produce one phone agent on
Freya, built ONLY from those files. Nothing in this skill or in the kit is a rule of the new brief: every
rule, number, date, name, sentence and outcome comes from the brief you were given. The reference agent
below shows HOW to express rules on this platform, never WHICH rules to use.

Scoring, so you know what matters: each customer passes only if the bank's records are exactly right
(outcome, reason, every promise's product/amount/date, notes, callbacks, transfers) AND a judge model
finds the conversation followed the brief AND the agent never said something untrue. No partial credit.
Each customer is run three times and counts only if all three pass. Customers talk like people: numbers
in two parts, self-corrections, chatter, questions back, amounts and dates in words.

Time: the whole run, tests included, must end before the deadline in your prompt (30 minutes from start).
Work in this order and do not polish past step 6 if time is short. Run Python as "$PYTHON".

## Files you use

- `agents/ref_ab.py`: the reference agent for the public Briefs A and B. 9-10 of 10 practice customers.
  Copy its structure. Every value in it marked `# BRIEF` came from those briefs and must be replaced.
- `kitlib/wf.py`: building blocks. `ToolAPI(path)` reads the tool API file (fields, enums, URL).
  `api_tool(...)` (a tool the model calls), `api_action(...)` (a call the engine makes on entry),
  `conversation(...)`, `code_node(...)`, `action_node(...)`, `end_node(...)`, `extract(...)`, `say(...)`,
  transitions `always / when_any / when_all / when_true / when_tool`, and `lint(workflow, api)`.
- `kitlib/datekit.py`: `date_lib(holidays, workdays)` returns Python source with `to_date, is_bd, add_bd,
  next_bd, bd_on_or_after, last_bd_of_week, week_start, say, money, day_table`. It runs inside the
  workflow's code nodes and hooks, and on this machine in tests.
- `tests/test_ref_hooks.py`: how to run the hooks locally. Copy it for your agent.
- `kitlib/chat.py <workflow_id> <practice case id> "line" "line" ...`: talk to the saved agent.
- `kitlib/why.py <results json>`: the timeline of each failed practice call.
- `tools/run_cases.py <agent_id> --brief A|B --out results/<slot>.json`: practice customers (only for
  the public briefs).

## Step 1. Write the spec (about 5 minutes)

Read every brief file and the tool API file completely. Write `out/<slot>/spec.md`, the brief as a
checklist you will build from. Raw material (mails, policy extracts, memos, code lists) is normal: a
later memo or mail overrides an earlier rule; a code list maps codes to meanings; ignore chatter that is
not a rule. Quote the source of every value. Cover all of these, writing "not in brief" where absent:

1. Call variables (names, formats) and what `now` means.
2. Opening: required first sentence, words forbidden before identity is verified, how to confirm the
   right person, how many asks, robot/AI and scam answers.
3. Someone else answers: what may be said, callback window rules, wrong number, deceased, relatives.
4. Identity: which questions, in which order, the tool field and answer format for each (dates as what
   format, day/month order), wrong-answer limit and what counts, special hints from the tool, declining.
5. Stating the debt: what to say, product names in words, which numbers.
6. Calendar: working days, holidays, how "next X" / "this X" / vague periods are read.
7. Dates: bands or categories, deadlines, allowed promise dates, what to offer when a date is not allowed.
8. Amounts: full amount, floor per product type, partial amounts, what to offer.
9. Persuasion: attempts per band, what each attempt proposes, when to stop, hardship handling.
10. Confirming and recording: read-back wording, one promise per product, failures and retries, the exact
    sentences required after recording.
11. Every other situation (paid, dispute, restructuring, human, scam, unanswerable question, refusal to
    talk) and the action and outcome for each.
12. Several products, if the brief allows them: order, per-product limits, notes, combined confirmation.
13. The outcome table: every (outcome, reason) pair and when it applies; how the final outcome is chosen
    when several things happened; which tools record what (notes, callbacks, transfers).
14. Every exact sentence the agent must say, verbatim.
15. Tool API: for each of the seven tools, the fields, required fields and allowed values. These can
    differ from the reference: use the file, not your memory.

## Step 2. Write the agent (about 10 minutes)

Copy `agents/ref_ab.py` to `out/<slot>/agent.py`, fix the paths (ROOT is the kit folder, the tool API
file is the one you were given), and change every part marked `# BRIEF` to follow your spec. Keep the
design, it is what passed:

- `setup` code node first (passthrough): computes date facts from `now` with `date_lib(<brief's
  holidays>, <brief's workdays>)` into `{{date_facts}}`, the callback window, and initial state
  variables. Never let the model compute a date: give it a calendar table and finished dates.
- `opening` conversation node: fixed `say(...)` first line built from the brief's required opening;
  an extraction enum (`customer` / `someone_else`) routes deterministically. close_call is offered with
  only the outcomes possible at that point (`enums=`).
- `third_party` node: callback tool with the window from the brief; no account facts in this node at all.
- `identity` node: the brief's questions in order; verify tool called on every answer; a post-hook adds
  `what_to_do_next` for each result (next question, retry, swapped day/month, limit reached); the route
  to the account step tests the "all verified" flag as both "true" and "True".
- `fetch_account` api_request node: the account call with a post-hook that computes, per product, the
  name in words, band, deadline, floor, attempts and attempt proposals, into `{{account_facts}}`, plus
  `products_json` for the guards, and recomputes `{{date_facts}}` (the chat route can skip `setup`).
- `negotiate` node: the brief's conversation rules, with the facts above in the prompt.
- Guards (pre-hooks): `create_promise` is checked against the brief's date and amount rules and one
  promise per product; a bad request is sent to a path that does not exist, so nothing reaches the bank,
  and the post-hook tells the agent exactly what to offer instead. `close_call`'s pre-hook derives the
  outcome and reason from what was recorded (transfers, promises, notes) following the brief's table,
  and drops the reason where the table has none. Write these from YOUR brief's rules.
- Post-hooks on every tool add `what_to_do_next`. After a failed write they say whether to retry.
  Writes the tool API says may be repeated after a service failure get `retries=1` when the brief says
  to try again.
- `end` end_call node, reached when close_call returns ok. The agent says goodbye before close_call.
- Prompts: system prompt = whole-call rules (language, one question at a time, robot/scam answers,
  no invented facts, after every tool result speak or call the next tool, one tool per message,
  goodbye before close_call). Node prompts say what to do and which tool to CALL when; never mention
  nodes or routing. Put exact sentences in quotes.

Platform rules kitlib already enforces, so do not fight it: tools only on conversation nodes, pre_actions
only on api_request/code nodes, every body field a leaf with its own default, enums copied from the tool
API, no `null`, no `{{` or `}}` inside code, every passthrough node ends with an `always` transition,
booleans tested as "true" and "True", `agent_config` left out. `lint()` runs before every save.

Hooks: read and write values only through `vars` (pre-hooks also get `config`, post-hooks `result`).
Wrap nothing in your own try: kitlib wraps hooks. A hook that crashes does nothing silently, so step 3.

## Step 3. Test the code locally (about 5 minutes)

Copy `tests/test_ref_hooks.py` to `out/<slot>/test_hooks.py` and rewrite its cases from YOUR spec: the
setup facts for a `now` in the brief's examples, deadlines per band, a weekend and a holiday date, an
amount below the floor, a second promise for the same product, the close_call outcome for each way a
call can end, every verify result. Run it. A failing assertion is a bug in your agent; fix the agent,
not the test, unless the test misread the brief. Then run `$PYTHON out/<slot>/agent.py` (lint) until clean.

Then run `$PYTHON kitlib/leftovers.py out/<slot>/agent.py <your brief files>`. It lists values and exact
sentences of the public Briefs A/B that are still in your agent but not in your brief. Replace each one
with your brief's rule or wording, or delete it; an example phrase of what a customer might say is fine
to keep only if it fits your brief. Also delete the prompt and code your agent does not use: the
reference has a one-product variant (NEGOTIATE_A, CLOSE_GUARD_A) and a several-products variant
(NEGOTIATE_B, CLOSE_GUARD_B). Keep exactly one. If your brief's customers can have more than one product
(final briefs can have up to three), keep the several-products variant and make it handle one product
too.

## Step 4. Save, publish, check (about 5 minutes)

`$PYTHON out/<slot>/agent.py --save` saves AND publishes (freya.save_workflow) into the same slot every
time. Wait 20 seconds before testing a new version.

- If your prompt gives practice customers: run the command it gives with `--out results/<slot>.json`
  added, once, read each FAIL
  with `$PYTHON kitlib/why.py results/<slot>.json`, fix the cause in agent.py, save, run again if time
  allows. Never more than two practice runs.
- Otherwise: one short chat with `kitlib/chat.py` using a public practice case id, only to see that the
  agent starts and speaks its opening line (the customer data will not match a new brief; that is fine).

## Step 5. Export and finish

`$PYTHON -c "import freya,json; s=json.load(open('.freya-agents.json'))['<slot>']; print(freya.export_workflow(s['workflow_id'], 'out/<slot>.workflow.json'))"`

Finish with one line: slot, workflow_id, agent_id, lint result, local tests result, practice result if any.

## What the final briefs will change (the organisers said so): handle each from the brief

- Other identity questions (the kit's customer simulator already knows postcode, birth year, company
  number, founded year, date of birth, phone digits). Take the questions, their order and each answer's
  format from the brief and from the verify tool's `field` enum in the tool API file. Write the identity
  prompt, the verify post-hook's "next question" text and the answer `field_help` from them. Say in the
  prompt how to normalise each answer before calling the tool (digits only, upper case, YYYY, YYYY-MM-DD).
- Customers who give an answer in two parts ("forty four" ... "zero one"): measured on 11 Oct, the agent
  kept asking for "all four digits", the customer repeated the first half, and the agent sent "0010":
  identity failed on 3 of 3 customers. The identity prompt must say: when only part of an answer comes,
  say only "Thank you, and the rest?", then JOIN the parts in order ("forty four" + "zero one" = 4401;
  "the eighth of January" + "nineteen ninety one" = 1991-01-08), never ask for the whole answer again,
  never send a part alone. Copy that wording from the reference's IDENTITY prompt and adapt the examples
  to your brief's questions. The same holds for amounts and dates later in the call.
- Business customers: if the brief calls a company and asks for a contact person, write the opening,
  the confirmation question and the "someone else" rules from the brief, not from the reference.
- Other limits, deadlines, bands, calendars: all in the setup code, the account post-hook and the
  guards, never only in prompts.
- Another outcome table: the close_call guard, the per-node close_call enums and every prompt that names
  an outcome must use exactly the new table's codes. Check each (outcome, reason) pair the guard can
  produce is in the table.
- Tool fields and allowed values can change: build every tool with `wf.api_tool` from the given tool API
  file and let `lint` compare. Never type a field name or enum value from memory.
- Several products (up to three): use the several-products design.
- Tie-break is the total promised amount on passed customers: always ask for the full amount first and
  never propose less than the brief requires before the customer asks.

## Lessons from the practice runs (each one failed a customer once)

- The judge counts literally. "Offered once" means the amount is named once in the whole call. When the
  brief says to offer something once, make that the only time it is said: merge it with the next step
  (e.g. name the floor together with the attempt-1 date in one sentence) and tell the agent never to
  repeat it. After a refusal, never add "just to be sure, you cannot pay?": that is an extra attempt.
  Write each persuasion attempt as one finished proposal in the facts and say: one proposal per attempt.
- Words the brief forbids or ties to an event are matched literally too. The opening said "this call is
  recorded" and the judge read it as claiming a promise was recorded. Phrase required disclosures with
  different words when they collide with a checked word ("we keep a recording of this call").
- A write that failed with a service error never reached the post-hook: the agent saw a raw error and
  gave up. Writes that the tool API says may be repeated get `retries=1` in the tool config (the
  platform retries once); the post-hook still handles the second failure.
- An HTTP error (404, 500) skips the post-hook: the agent sees only "API request failed: <raw body>".
  So a guard never blocks by breaking the URL. It rewrites the blocked write into a harmless read of the
  same API (`get_account` with the same customer_id: status 200, changes nothing), and the write's
  post-hook, seeing the block flag, clears the result and says exactly what to offer instead.
- Separate "too much" from "no". An offer the brief reserves for one situation (the floor when the amount
  is too much) must say so, or the agent uses it as an extra attempt after a plain refusal.
- With several products, the agent mixes up whose deadline is whose. Facts list each product with its own
  deadline; the prompt says to check a shared date against EACH product; the guard catches the rest.
- After `--save`, wait 20 seconds before a test: a run started at once can still use the old version.
- The quick chat route skips the first code node, so anything a later node needs (today's date facts)
  is recomputed where it is used (the account post-hook does this).
- The dialogue model will compute dates from the real clock if it has no date facts. Always give it
  "Today is <now>" and a calendar table, and let the guard catch the rest.
- Extraction enums route reliably (who is on the line); results route deterministically (all verified,
  close_call ok). Keep `matches_intent` for nothing that a variable can decide.

## Rules

- Never edit the agent on the platform by hand. Change agent.py and save.
- Do not use git or touch files outside out/<slot>/ and results/. The organisers rerun this builder.
- Run every command from the kit folder (the working directory you start in); never `cd` into out/<slot>/.
- Never write a value into agent.py that is not in the brief or the tool API file you were given.
- Never tell the customer something is recorded unless the tool returned ok.
- Prefer code (hooks, code nodes, routes on tool results) over prompt rules for anything a rule can
  decide: dates, amounts, limits, counts, outcomes.
- If something does not fit the reference design (a new kind of step, a rule with no place), add a node
  or a hook for it in the same style rather than squeezing it into a prompt.
