# build-the-builder

An agent that builds agents, for YC x Freya's Build the Builder hackathon (10-11 Oct 2026).

Given a task description and its tools, it:

1. **compiles the task into a checklist** of hard rules, marking the critical ones (security, money, privacy, order of steps),
2. drafts a phone agent that has to satisfy every rule,
3. **invents test customers, one built to break each critical rule**, plus a mix of easy, confused and off-topic callers,
4. simulates every call **K times** (a model plays the customer and the backend tools),
5. grades each call against the checklist: **0 if a critical rule broke**, else the share of checks passed. Each customer counts its **worst** run,
6. revises the agent from its failures, choosing the parent from a **Pareto pool** (every candidate best on some customer) rather than only the top one,
7. **picks the winner on fresh customers** it never trained on,
8. adds phone rules to every agent: short spoken turns, one question at a time, read numbers back.

Why these choices:
- τ-bench (Yao et al. 2024, arXiv 2406.12045) found strong agents succeed on under half of customer-service tasks and are inconsistent across repeats, and introduced pass^k. Hence the K plays per customer, scored by the worst.
- GEPA (Agrawal et al., ICLR 2026, arXiv 2507.19457) reports Pareto-based candidate selection beating greedy selection. Hence the pool.
- Any step that fails (rate limit, outage, bad JSON) is retried, and a failed round never loses the agents already built, because nobody can fix the builder during judging.

## Run it

Python 3.10+, standard library only.

```bash
LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=... python run.py tasks/bank_card_freeze.json --rounds 4 --train 4 --val 3 --k 2
```

Output goes to `out/<task id>/agent.json` (the agent) and `out/<task id>/report.json` (the extracted rules, every candidate's scores and failures, validation scores, model calls used). `WORKERS` sets how many calls run in parallel (default 4).

Model backends (`LLM_PROVIDER`): `anthropic`, `openai` (any OpenAI-compatible endpoint: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`), or `stub` (canned answers, no network).
Set `LLM_MODEL_<STEP>` (e.g. `LLM_MODEL_JUDGE`, `LLM_MODEL_REVISE`, `LLM_MODEL_DRAFT`) to run one step on a different model: a strong model writes and judges, a fast one plays the caller (`user`) and the backend (`tool`).

## Test

```bash
python test_builder.py
```

`python mutate.py` then undoes key fixes one at a time and confirms the tests fail for each; a test that passes with its fix removed checks nothing.

`test_builder.py` runs the whole loop on the stub model, which is rigged so a critical breach scores 0 and later revisions score worse than the best one. It checks that the builder keeps the best agent, re-scores it on fresh customers, adds the phone rules, and survives a step failing mid-run.

## Layout

- `builder/core.py`: the loop (draft, scenarios, simulate, judge, revise, build)
- `builder/llm.py`: the one door to a model
- `builder/platform.py`: the only Freya-specific code, turning an agent into their platform's format
- `builder/stub.py`: canned answers for tests
- `run.py`: the command above
